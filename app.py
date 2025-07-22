from flask import Flask, render_template, request, redirect, session, url_for, flash
from models import db, User, Product, CartItem, Order, OrderItem , Rating
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///homemade_pickles.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your-secret-key'

db.init_app(app)
migrate = Migrate(app, db)

# ---------- Auth Helpers ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------- Routes ----------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        role = request.form['role']
        is_admin = True if role == 'admin' else False

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
            return redirect(url_for('register'))

        user = User(username=username, email=email, password=password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')  # safer than ['email']
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            flash("Login successful.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "error")
            return redirect(url_for('login'))
    return render_template('login.html')
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])

    if user.is_admin:
        products = Product.query.all()
        for product in products:
            avg = db.session.query(db.func.avg(Rating.stars)).filter_by(product_id=product.id).scalar()
            product.avg_rating = avg

        orders = Order.query.all()
        for order in orders:
            rating = Rating.query.filter_by(order_id=order.id).first()
            order.rating = rating

        customers = User.query.filter_by(is_admin=False).all()
        admins = User.query.filter_by(is_admin=True).all()

        return render_template('admin_dashboard.html', customers=customers, admins=admins,
                               products=products, orders=orders)
    else:
        orders = Order.query.filter_by(user_id=user.id).all()
        return render_template('customer_dashboard.html', user=user, orders=orders)

@app.route('/products')
@login_required
def products():
    products = Product.query.all()
    return render_template('products.html', products=products)

@app.route('/add-to-cart', methods=['POST'])
@login_required
def add_to_cart():
    name = request.form.get('name')
    price = float(request.form.get('price'))
    description = request.form.get('description')
    category = request.form.get('category')
    quantity = int(request.form.get('quantity', 1))
    user_id = session['user_id']

    product = Product.query.filter_by(name=name).first()
    if not product:
        product = Product(name=name, description=description, price=price,
                          category=category, stock=100)
        db.session.add(product)
        db.session.commit()

    cart_item = CartItem.query.filter_by(user_id=user_id, product_id=product.id).first()
    if cart_item:
        cart_item.quantity += quantity
    else:
        cart_item = CartItem(user_id=user_id, product_id=product.id, quantity=quantity)
        db.session.add(cart_item)

    db.session.commit()
    flash("Item added to cart.", "success")
    return redirect(url_for('products'))

@app.route('/cart')
@login_required
def cart():
    user_id = session['user_id']
    cart_items = CartItem.query.filter_by(user_id=user_id).all()
    valid_cart = [item for item in cart_items if item.product is not None]
    total = sum(item.product.price * item.quantity for item in valid_cart)
    return render_template('cart.html', cart=valid_cart, total_price=total)

@app.route('/checkout')
@login_required
def checkout():
    user_id = session['user_id']
    cart_items = CartItem.query.filter_by(user_id=user_id).all()
    if not cart_items:
        flash("Your cart is empty.", "info")
        return redirect(url_for('products'))
    return render_template('address_form.html')

@app.route('/process-checkout', methods=['POST'])
@login_required
def process_checkout():
    user_id = session['user_id']
    address = request.form.get('address')
    cart_items = CartItem.query.filter_by(user_id=user_id).all()

    if not address or not cart_items:
        flash("Address is required and cart must not be empty.", "error")
        return redirect(url_for('checkout'))

    total = sum(item.product.price * item.quantity for item in cart_items if item.product)
    new_order = Order(user_id=user_id, total=total, address=address)
    db.session.add(new_order)
    db.session.commit()

    for item in cart_items:
        if item.product:
            order_item = OrderItem(order_id=new_order.id, product_id=item.product_id,
                                   quantity=item.quantity, price=item.product.price)
            db.session.add(order_item)
            db.session.delete(item)

    db.session.commit()
    return redirect(url_for('payment_success', order_id=new_order.id))

@app.route('/payment-success/<int:order_id>')
@login_required
def payment_success(order_id):
    return render_template('payment_success.html', order_id=order_id)

@app.route('/track-order/<int:order_id>')
@login_required
def track_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('track_order.html', order=order)

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/remove-from-cart', methods=['POST'])
@login_required
def remove_from_cart():
    product_id = request.form['product_id']
    user_id = session.get('user_id')

    if not product_id or not user_id:
        flash("Invalid request. Please try again.", "danger")
        return redirect(url_for('cart'))

    try:
        item_to_remove = CartItem.query.filter_by(user_id=user_id, product_id=product_id).first()
        if item_to_remove:
            db.session.delete(item_to_remove)
            db.session.commit()
            flash("Item removed from your cart.", "info")
        else:
            flash("Item not found in your cart.", "warning")
    except Exception as e:
        flash(f"Error removing item: {e}", "danger")

    return redirect(url_for('cart'))

@app.route('/submit-rating/<int:order_id>', methods=['POST'])
@login_required
def submit_rating(order_id):
    try:
        stars = int(request.form['stars'])
    except (ValueError, TypeError):
        flash("Invalid rating value.", "danger")
        return redirect(url_for('payment_success', order_id=order_id))

    user_id = session['user_id']
    order = Order.query.get_or_404(order_id)

    for item in order.order_items:
        rating = Rating(user_id=user_id, product_id=item.product_id, order_id=order.id, stars=stars)
        db.session.add(rating)

    db.session.commit()
    flash("Thanks for your rating!", "success")
    return redirect(url_for('dashboard'))
# ---------- Run ----------
if __name__ == "__main__":
    app.run()