from flask import Flask, render_template, request, redirect, session, url_for, flash
from models import db, User, Product, CartItem, Order, OrderItem, Feedback
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///homemade_pickles.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your-secret-key'

db.init_app(app)

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
        email    = request.form['email']
        password = generate_password_hash(request.form['password'])
        role     = request.form['role']
        is_admin = True if role == 'admin' else False

        if User.query.filter_by(email=email).first():
            return "Email already registered. Please use a different one."

        user = User(username=username, email=email, password=password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user     = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            return redirect('/dashboard')
        else:
            return 'Invalid Credentials'
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    if user.is_admin:
        customers = User.query.filter_by(is_admin=False).all()
        admins = User.query.filter_by(is_admin=True).all()
        products = Product.query.all()
        orders = Order.query.all()
        feedbacks = Feedback.query.order_by(Feedback.timestamp.desc()).all()

        return render_template('admin_dashboard.html',
                               customers=customers,
                               admins=admins,
                               products=products,
                               orders=orders,
                               feedbacks=feedbacks)
    else:
        orders = Order.query.filter_by(user_id=user.id).all()
        return render_template('customer_dashboard.html', user=user, orders=orders)

@app.route('/products')
@login_required
def products():
    products = Product.query.all()
    print(f"PRODUCT COUNT: {len(products)}")  # Debug line
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

    # Check if product already exists in DB; if not, add it
    product = Product.query.filter_by(name=name).first()
    if not product:
        product = Product(name=name, description=description, price=price, category=category, stock=100)
        db.session.add(product)
        db.session.commit()

    # Add to cart
    existing_item = CartItem.query.filter_by(user_id=user_id, product_id=product.id).first()
    if existing_item:
        existing_item.quantity += quantity
    else:
        new_item = CartItem(user_id=user_id, product_id=product.id, quantity=quantity)
        db.session.add(new_item)

    db.session.commit()
    flash("Item added to cart.")
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
        flash("Your cart is empty.")
        return redirect(url_for('products'))
    return render_template('address_form.html')  # Shows address entry form


@app.route('/process-checkout', methods=['POST'])
@login_required
def process_checkout():
    user_id = session['user_id']
    address = request.form.get('address')
    cart_items = CartItem.query.filter_by(user_id=user_id).all()

    if not address or not cart_items:
        flash("Address is required and cart must not be empty.")
        return redirect(url_for('checkout'))

    total = sum(item.product.price * item.quantity for item in cart_items if item.product)

    # Create order with address
    new_order = Order(user_id=user_id, total=total, address=address)
    db.session.add(new_order)
    db.session.commit()

    for item in cart_items:
        if item.product:
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=item.product_id,
                quantity=item.quantity,
                price=item.product.price
            )
            db.session.add(order_item)
            db.session.delete(item)  # Clear from cart

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

@app.route('/feedback', methods=['GET', 'POST'])
@login_required
def feedback():
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            new_feedback = Feedback(user_id=session['user_id'], content=content)
            db.session.add(new_feedback)
            db.session.commit()
            flash('Thank you for your feedback!', 'success')
            return redirect(url_for('feedback'))
    return render_template('feedback.html')

# ---------- Run ----------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

