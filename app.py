from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cctv.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your-secret-key-2026-default'  # В production поменяйте на надежный

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)  # Добавлено поле email
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)  # На будущее для блокировки
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ServiceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default='new')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Связь с пользователем


class Calculation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    room_length = db.Column(db.Float)
    room_width = db.Column(db.Float)
    room_type = db.Column(db.String(50))
    camera_count = db.Column(db.Integer)
    camera_type = db.Column(db.String(100))
    total_price = db.Column(db.Float)
    # Связываем расчет с пользователем, который его сохранил
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    type = db.Column(db.String(50))  # camera, recorder, accessory
    price = db.Column(db.Float)
    specs = db.Column(db.String(200))
    icon = db.Column(db.String(50))
    image = db.Column(db.String(100), default='default.jpg')


# ================= ЛОГИКА РАСЧЕТА =================

def calculate_cameras(length, width, room_type):
    area = length * width
    perimeter = 2 * (length + width)

    if room_type == 'office':
        base_count = max(2, round(area / 20))
        camera_type = 'Купольная камера 2MP (внутренняя)'
        camera_price = 3500
    elif room_type == 'warehouse':
        base_count = max(3, round(area / 25) + 1)
        camera_type = 'Уличная камера 2MP (IP67)'
        camera_price = 4800
    elif room_type == 'entrance':
        base_count = max(2, round(perimeter / 15))
        camera_type = 'Купольная камера 4MP (широкий угол)'
        camera_price = 5900
    else:
        base_count = max(2, round(area / 20))
        camera_type = 'Стандартная камера 2MP'
        camera_price = 3200

    return {
        'count': base_count,
        'type': camera_type,
        'price_per_unit': int(camera_price),
        'total': int(base_count * camera_price),
        'area': int(area),
        'perimeter': int(perimeter)
    }

def calculate_cable(length, width, camera_count):
    diagonal = (length**2 + width**2) ** 0.5
    avg_distance = diagonal / 2 + 5
    total = camera_count * avg_distance * 1.1
    return round(total, 1)

def calculate_recorder(camera_count):
    if camera_count <= 4:
        return {'name': 'Видеорегистратор 4 канала (1TB)', 'price': 7500}
    elif camera_count <= 8:
        return {'name': 'Видеорегистратор 8 каналов (2TB)', 'price': 12500}
    else:
        return {'name': 'Видеорегистратор 16 каналов (4TB)', 'price': 18900}

def calculate_power(camera_count):
    units = (camera_count + 3) // 4
    return {'units': units, 'price_per_unit': 1850, 'total': units * 1850}


# ================= КОНТЕКСТНЫЙ ПРОЦЕССОР (ДЛЯ ШАБЛОНОВ) =================
@app.context_processor
def utility_processor():
    user = None
    user_is_admin = False
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user_is_admin = user.is_admin
    return dict(current_user=user, user_is_admin=user_is_admin)


# ================= МАРШРУТЫ (СТРАНИЦЫ) =================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/calculate', methods=['POST'])
def calculate():
    try:
        length = float(request.form.get('length', 5))
        width = float(request.form.get('width', 4))
        room_type = request.form.get('room_type', 'office')
        audio = request.form.get('audio') == 'on'
        night_vision = request.form.get('night_vision') == 'on'

        cameras = calculate_cameras(length, width, room_type)

        if night_vision:
            cameras['price_per_unit'] += 800
            cameras['total'] = cameras['count'] * cameras['price_per_unit']
        if audio:
            cameras['price_per_unit'] += 500
            cameras['total'] = cameras['count'] * cameras['price_per_unit']

        cable_length = calculate_cable(length, width, cameras['count'])
        cable_price = 18
        cable_total = cable_length * cable_price

        recorder = calculate_recorder(cameras['count'])
        power = calculate_power(cameras['count'])
        total = cameras['total'] + recorder['price'] + cable_total + power['total']

        result = {
            'cameras': {
                'count': cameras['count'],
                'type': cameras['type'],
                'price_per_unit': int(cameras['price_per_unit']),
                'total': int(cameras['total'])
            },
            'recorder': recorder,
            'cable': {
                'length': int(cable_length),
                'price_per_meter': int(cable_price),
                'total': int(cable_total)
            },
            'power': {
                'units': power['units'],
                'price_per_unit': int(power['price_per_unit']),
                'total': int(power['total'])
            },
            'total': int(total)
        }

        return render_template('index.html', result=result, form_data={
            'length': length,
            'width': width,
            'room_type': room_type,
            'audio': audio,
            'night_vision': night_vision
        })

    except Exception as e:
        return render_template('index.html', error=str(e))

@app.route('/smeta/<int:calc_id>')
def smeta_print(calc_id):
    calc = Calculation.query.get_or_404(calc_id)
    return render_template('smeta_print.html', calc=calc)

@app.route('/submit_request', methods=['POST'])
def submit_request():
    name = request.form.get('name')
    phone = request.form.get('phone')
    message = request.form.get('message')

    new_request = ServiceRequest(
        name=name,
        phone=phone,
        message=message,
        status='new',
        user_id=session.get('user_id')
    )
    db.session.add(new_request)
    db.session.commit()

    return render_template('request_success.html', name=name)


@app.route('/save_calculation', methods=['POST'])
def save_calculation():
    try:
        calc = Calculation(
            room_length=float(request.form.get('length', 0)),
            room_width=float(request.form.get('width', 0)),
            room_type=request.form.get('room_type', ''),
            camera_count=int(request.form.get('camera_count', 0)),
            camera_type=request.form.get('camera_type', ''),
            total_price=float(request.form.get('total_price', 0)),
            user_id=session.get('user_id')
        )
        db.session.add(calc)
        db.session.commit()
        flash('Расчёт успешно сохранён!', 'success')
        return redirect(url_for('history'))
    except Exception as e:
        flash(f'Ошибка сохранения: {e}', 'danger')
        return redirect(url_for('index'))


@app.route('/product/<int:product_id>')
def product(product_id):
    item = Equipment.query.get_or_404(product_id)
    return render_template('product.html', item=item)


@app.route('/history')
def history():
    # Если пользователь не авторизован, перенаправляем на логин
    if 'user_id' not in session:
        flash('Войдите, чтобы посмотреть историю расчётов', 'warning')
        return redirect(url_for('login'))
    calculations = Calculation.query.filter_by(user_id=session['user_id']).order_by(Calculation.date.desc()).all()
    return render_template('history.html', calculations=calculations)


@app.route('/history/delete/<int:id>')
def delete_calculation(id):
    calc = Calculation.query.get_or_404(id)
    # Проверяем, что расчет принадлежит текущему пользователю
    if calc.user_id != session.get('user_id'):
        flash('Нет прав на удаление этого расчета', 'danger')
        return redirect(url_for('history'))
    db.session.delete(calc)
    db.session.commit()
    flash('Расчёт удалён', 'success')
    return redirect(url_for('history'))


@app.route('/catalog')
def catalog():
    cameras = Equipment.query.filter_by(type='camera').all()
    recorders = Equipment.query.filter_by(type='recorder').all()
    accessories = Equipment.query.filter_by(type='accessory').all()
    return render_template('catalog.html', cameras=cameras, recorders=recorders, accessories=accessories)


@app.route('/contacts')
def contacts():
    return render_template('contacts.html')


@app.route('/print/<int:calc_id>')
def print_invoice(calc_id):
    calc = Calculation.query.get_or_404(calc_id)
    return render_template('print_invoice.html', calc=calc)


# ================= АУТЕНТИФИКАЦИЯ И ПОЛЬЗОВАТЕЛИ =================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует.', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.id
        flash('Регистрация прошла успешно!', 'success')
        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            flash(f'Добро пожаловать, {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверный email или пароль.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))


# ================= АДМИН-ПАНЕЛЬ =================
def admin_required():
    if 'user_id' not in session:
        return False
    user = User.query.get(session['user_id'])
    return user and user.is_admin

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = User.query.filter_by(username=username, is_admin=True).first()
        if admin and admin.check_password(password):
            session['user_id'] = admin.id
            return redirect(url_for('admin_dashboard'))
        error = 'Неверный логин или пароль администратора'
        return render_template('admin_login.html', error=error)
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not admin_required():
        return redirect(url_for('admin_login'))
    products = Equipment.query.all()
    requests = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).all()
    users = User.query.all()
    stats = {'products': len(products), 'requests': len(requests), 'users': len(users)}
    return render_template('admin/dashboard.html', products=products, requests=requests, users=users, stats=stats)

@app.route('/admin/product/add', methods=['GET', 'POST'])
def add_product():
    if not admin_required():
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        product = Equipment(
            name=request.form['name'],
            type=request.form['type'],
            price=int(request.form['price']),
            specs=request.form['specs'],
            image=request.form.get('image', 'default.jpg')
        )
        db.session.add(product)
        db.session.commit()
        flash('Товар добавлен', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/product_form.html')

@app.route('/admin/product/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    product = Equipment.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.type = request.form['type']
        product.price = int(request.form['price'])
        product.specs = request.form['specs']
        product.image = request.form.get('image', product.image)
        db.session.commit()
        flash('Товар обновлён', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/product_form.html', product=product)

@app.route('/admin/product/delete/<int:id>')
def delete_product(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    product = Equipment.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Товар удалён', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/request/<int:id>/status', methods=['POST'])
def update_request_status(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    req = ServiceRequest.query.get_or_404(id)
    req.status = request.form['status']
    db.session.commit()
    flash('Статус заявки обновлён', 'success')
    return redirect(url_for('admin_dashboard'))
# ================= ДОПОЛНИТЕЛЬНЫЕ АДМИН-МАРШРУТЫ =================

@app.route('/admin/request/delete/<int:id>')
def delete_request(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    req = ServiceRequest.query.get_or_404(id)
    db.session.delete(req)
    db.session.commit()
    flash('Заявка удалена', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/block/<int:id>')
def block_user(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    user = User.query.get_or_404(id)
    user.is_active = not user.is_active
    db.session.commit()
    status = 'заблокирован' if not user.is_active else 'разблокирован'
    flash(f'Пользователь {user.username} {status}', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/delete/<int:id>')
def delete_user(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash(f'Пользователь {user.username} удалён', 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/calculation/delete/<int:id>')
def delete_calculation_admin(id):
    if not admin_required():
        return redirect(url_for('admin_login'))
    calc = Calculation.query.get_or_404(id)
    db.session.delete(calc)
    db.session.commit()
    flash('Расчёт удалён', 'success')
    return redirect(url_for('admin_dashboard'))

# ================= ЗАПОЛНЕНИЕ БАЗЫ НАЧАЛЬНЫМИ ДАННЫМИ =================
def init_db():
    db.drop_all()
    db.create_all()

    # Создаём админа
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@example.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)

    # Заполняем каталог, если он пуст
    if Equipment.query.count() == 0:
        equipment_data = [
            Equipment(name='Купольная камера 2MP', type='camera', price=3500, specs='2 Мп, ИК до 20м, встроенный микрофон', icon='fa-camera'),
            Equipment(name='Уличная камера 2MP', type='camera', price=4800, specs='2 Мп, IP67, ИК до 30м, ночное видение', icon='fa-camera'),
            Equipment(name='Купольная камера 4MP', type='camera', price=5900, specs='4 Мп, широкий угол 110°, WDR', icon='fa-camera'),
            Equipment(name='PTZ камера 5MP', type='camera', price=18900, specs='5 Мп, поворот 360°, оптический зум 20x', icon='fa-video'),
            Equipment(name='Видеорегистратор 4 канала', type='recorder', price=7500, specs='1TB HDD, H.265+, удаленный доступ', icon='fa-hdd'),
            Equipment(name='Видеорегистратор 8 каналов', type='recorder', price=12500, specs='2TB HDD, поддержка AI детекции', icon='fa-hdd'),
            Equipment(name='Видеорегистратор 16 каналов', type='recorder', price=18900, specs='4TB HDD, 4K запись, RAID', icon='fa-server'),
            Equipment(name='Кабель UTP Cat.5e', type='accessory', price=18, specs='медный, 305м в бухте', icon='fa-plug'),
            Equipment(name='Блок питания 12V 10A', type='accessory', price=1850, specs='на 4 камеры, защита от КЗ', icon='fa-battery-full'),
            Equipment(name='Кронштейн настенный', type='accessory', price=450, specs='металлический, регулируемый', icon='fa-mount'),
        ]
        db.session.add_all(equipment_data)

    db.session.commit()
    print("База данных инициализирована. Админ: admin / admin123")

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, host='127.0.0.1', port=5000)