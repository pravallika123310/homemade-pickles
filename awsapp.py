from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
from datetime import datetime
import json,uuid
from decimal import Decimal

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_12345'  # Change for production!

dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')  # e.g., 'us-east-1'
users_table = dynamodb.Table('Users')
orders_table = dynamodb.Table('Orders')
products_table = dynamodb.Table('Products')
cart_table = dynamodb.Table('CartItems')

# # ================== TEMPORARY DATA STORES ==================


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
        user_id = str(uuid.uuid4())

        existing = users_table.get_item(Key={'email': email})
        if 'Item' in existing:
            flash("Email already registered.", "error")
            return redirect(url_for('register'))

        users_table.put_item(Item={
            'user_id': user_id,
            'username': username,
            'email': email,
            'password': password,
            'role': role
        })

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        response = users_table.get_item(Key={'email': email})
        user = response.get('Item')

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['user_id']
            session['is_admin'] = True if user['role'] == 'admin' else False
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
    user_id = session['user_id']

    # Retrieve the user info from DynamoDB using scan + filter
    response = users_table.scan(
        FilterExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id}
    )
    users = response.get('Items', [])
    user = users[0] if users else None

    if not user:
        flash("User not found.", "error")
        return redirect(url_for('login'))

    if user['role'] == 'admin':
        customers = users_table.scan(
            FilterExpression='role = :r',
            ExpressionAttributeValues={':r': 'customer'}
        )['Items']

        admins = users_table.scan(
            FilterExpression='role = :r',
            ExpressionAttributeValues={':r': 'admin'}
        )['Items']

        # You can add products and orders if you create respective DynamoDB tables
        return render_template('admin_dashboard.html',
                               customers=customers,
                               admins=admins,
                               products=[],  # Placeholder
                               orders=[],    # Placeholder
                               feedbacks=[]) # Placeholder
    else:
        user_orders = orders_table.scan(
            FilterExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id}
        )['Items']
        return render_template('customer_dashboard.html', user=user, orders=user_orders)

@app.route('/products')
@login_required
def products():
    response = products_table.scan()
    products = response.get('Items', [])
    return render_template('products.html', products=products)

@app.route('/add-to-cart', methods=['POST'])
@login_required
def add_to_cart():
    user_id = session['user_id']
    product_id = request.form.get('product_id')
    name = request.form.get('name')
    price = float(request.form.get('price'))
    quantity = int(request.form.get('quantity', 1))

    # Check if cart item exists
    response = cart_table.get_item(Key={'user_id': user_id, 'product_id': product_id})
    existing_item = response.get('Item')

    if existing_item:
        new_quantity = existing_item['quantity'] + quantity
        cart_table.put_item(Item={
            'user_id': user_id,
            'product_id': product_id,
            'name': name,
            'price': Decimal(str(price)),
            'quantity': new_quantity
        })
    else:
        cart_table.put_item(Item={
            'user_id': user_id,
            'product_id': product_id,
            'name': name,
            'price': Decimal(str(price)),
            'quantity': quantity
        })

    flash("Item added to cart.", "success")
    return redirect(url_for('products'))
@app.route('/cart')
@login_required
def cart():
    user_id = session['user_id']

    # Fetch cart items for this user
    response = cart_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('user_id').eq(user_id)
    )
    cart_items = response.get('Items', [])

    # Calculate total price
    total_price = sum(item['price'] * item['quantity'] for item in cart_items)

    return render_template('cart.html', cart=cart_items, total_price=total_price)
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

    # Fetch cart items from DynamoDB
    response = cart_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('user_id').eq(user_id)
    )
    cart_items = response.get('Items', [])

    if not address or not cart_items:
        flash("Address is required and cart must not be empty.", "error")
        return redirect(url_for('checkout'))

    # Calculate total
    total = sum(item['price'] * item['quantity'] for item in cart_items)

    # Create order data
    order_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()

    orders_table.put_item(Item={
        'order_id': order_id,
        'user_id': user_id,
        'address': address,
        'total': Decimal(str(total)),
        'items': cart_items,
        'timestamp': timestamp
    })

    # Clear cart items (delete one by one)
    for item in cart_items:
        cart_table.delete_item(Key={
            'user_id': user_id,
            'product_id': item['product_id']
        })

    flash("Order placed successfully!", "success")
    return redirect(url_for('payment_success', order_id=order_id))

@app.route('/payment-success/<int:order_id>')
@login_required
def payment_success(order_id):
    return render_template('payment_success.html', order_id=order_id)

@app.route('/track-order/<string:order_id>')
@login_required
def track_order(order_id):
    response = orders_table.get_item(Key={'order_id': order_id})
    order = response.get('Item')

    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('dashboard'))

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
            feedback_id = str(uuid.uuid4())
            timestamp = datetime.now().isoformat()

            feedback_table.put_item(Item={
                'feedback_id': feedback_id,
                'user_id': session['user_id'],
                'content': content,
                'timestamp': timestamp
            })

            flash("Thank you for your feedback!", "success")
            return redirect(url_for('feedback'))

    return render_template('feedback.html')

# ---------- Run ----------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 