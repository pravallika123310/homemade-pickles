from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
from datetime import datetime
import uuid
from functools import wraps
from decimal import Decimal
from boto3.dynamodb.conditions import Key

AWS_REGION = 'us-east-1'
USERS_TABLE_NAME = 'Users'
APPDATA_TABLE_NAME = 'AppData'
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:PickleOrderUpdates"  

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
users_table = dynamodb.Table(USERS_TABLE_NAME)
appdata_table = dynamodb.Table(APPDATA_TABLE_NAME)
sns = boto3.client('sns', region_name=AWS_REGION)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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

        flash("Registration successful!", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            response = users_table.get_item(Key={'email': email})
        except Exception as e:
            flash("Login failed. Please try again later.", "error")
            print("DynamoDB error:", e)
            return redirect(url_for('login'))

        user = response.get('Item')

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['is_admin'] = (user.get('role') == 'admin')
            session['email'] = user['email']
            flash("Login successful.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "error")
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    username = user['username']
    is_admin = user['is_admin']
    if is_admin:
        all_items = appdata_table.scan()['Items']
        users = [item for item in all_items if item.get('SK', '').startswith('PROFILE#') and not item.get('is_admin')]
        products = [item for item in all_items if item.get('PK', '').startswith('PRODUCT#') and item.get('SK') == 'DETAILS']
        orders = [item for item in all_items if item.get('SK') == 'DETAILS' and item.get('PK', '').startswith('ORDER#')]
        feedbacks = [item for item in all_items if item.get('PK', '').startswith('FEEDBACK#')]
        product_ratings = {}
        for product in products:
            product_id = product['PK'].split('#')[1]
            rating_response = appdata_table.query(
                KeyConditionExpression=Key('PK').eq(f'RATING#{product_id}')
            )
            rating_items = rating_response.get('Items', [])

            if rating_items:
                total_rating = sum(item.get('rating', 0) for item in rating_items)
                avg_rating = round(total_rating / len(rating_items), 1)
            else:
                avg_rating = 0.0  

            product_ratings[product_id] = avg_rating
        return render_template(
            'admin_dashboard.html',
            users=users,
            products=products,
            orders=orders,
            feedbacks=feedbacks,
            product_ratings=product_ratings
        )
    else:
        orders = appdata_table.query(
            KeyConditionExpression=Key('PK').eq(f'ORDER#{username}')
        )['Items']
        return render_template('customer_dashboard.html', user=user, orders=orders)


@app.route('/products')
@login_required
def products():
    response = appdata_table.scan(
        FilterExpression=Key('PK').begins_with('PRODUCT#')
    )
    items = response.get('Items', [])
    return render_template('products.html', products=items)

@app.route('/add-product', methods=['POST'])
@login_required
def add_product():
    if not session.get('is_admin'):
        return redirect(url_for('dashboard'))

    name = request.form['name']
    price = float(request.form['price'])
    product_id = str(uuid.uuid4())
    description = request.form.get('description')
    category = request.form.get('category')
    quantity = int(request.form.get('quantity', 1))
    user_id = session['user_id']

    appdata_table.put_item(Item={
    'PK': f'PRODUCT#{product_id}',
    'SK': 'DETAILS',
    'product_id': product_id,
    'name': name,
    'price': Decimal(str(price)),
    'description': description,
    'category': category,
    'quantity': quantity,
    'created_by': user_id,
    'created_at': datetime.datetime.now().isoformat()
})

    flash("Product added!", "success")
    return redirect(url_for('products'))

@app.route('/add-to-cart', methods=['POST'])
@login_required
def add_to_cart():
    user_id = session['user_id']
    product_id = request.form['product_id']
    name = request.form['name']
    price = float(request.form['price'])
    quantity = int(request.form.get('quantity', 1))

    appdata_table.put_item(Item={
        'PK': f'CART#{user_id}',
        'SK': f'PRODUCT#{product_id}',
        'product_id': product_id,
        'name': name,
        'price': Decimal(str(price)),
        'quantity': quantity
    })

    flash("Added to cart!", "success")
    return redirect(url_for('products'))

@app.route('/cart')
@login_required
def cart():
    user_id = session['user_id']
    response = appdata_table.query(
        KeyConditionExpression=Key('PK').eq(f'CART#{user_id}')
    )
    items = response.get('Items', [])
    total = sum(item['price'] * item['quantity'] for item in items)
    return render_template('cart.html', cart=items, total_price=total)

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    user_id = session['user_id']
    address = request.form.get('address')
    order_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()

    response = appdata_table.query(
        KeyConditionExpression=Key('PK').eq(f'CART#{user_id}')
    )
    cart_items = response.get('Items', [])

    if not cart_items:
        flash("Cart is empty.", "error")
        return redirect(url_for('cart'))

    total = sum(item['price'] * item['quantity'] for item in cart_items)

    appdata_table.put_item(Item={
        'PK': f'ORDER#{order_id}',
        'SK': 'DETAILS',
        'order_id': order_id,
        'user_id': user_id,
        'address': address,
        'items': cart_items,
        'total': Decimal(str(total)),
        'timestamp': timestamp
    })

    message = f"Order #{order_id} placed by {session.get('email')}. Total: ₹{total}"
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject="New Pickle Order Notification"
        )
    except Exception as e:
        print("SNS publish failed:", str(e))

    for item in cart_items:
        appdata_table.delete_item(
            Key={'PK': f'CART#{user_id}', 'SK': f"PRODUCT#{item['product_id']}"}
        )

    flash("Order placed successfully!", "success")
    return redirect(url_for('payment_success', order_id=order_id))

@app.route('/payment-success/<string:order_id>')
@login_required
def payment_success(order_id):
    return render_template('payment_success.html', order_id=order_id)

@app.route('/track-order/<string:order_id>')
@login_required
def track_order(order_id):
    response = appdata_table.get_item(Key={'PK': f'ORDER#{order_id}', 'SK': 'DETAILS'})
    order = response.get('Item')
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for('dashboard'))
    return render_template('track_order.html', order=order)

@app.route('/remove-from-cart/<string:product_id>', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    user_id = session['user_id']
    try:
        appdata_table.delete_item(
            Key={
                'PK': f'CART#{user_id}',
                'SK': f'PRODUCT#{product_id}'
            }
        )
        flash("Item removed from cart.", "info")
    except Exception as e:
        flash("Failed to remove item.", "danger")
        print("Delete error:", str(e))
    return redirect(url_for('cart'))


@app.route('/submit-rating/<order_id>', methods=['POST'])
@login_required
def submit_rating(order_id):
    rating = int(request.form['rating'])
    user_id = session['user_id']
    response = appdata_table.get_item(Key={
        'PK': f'ORDER#{order_id}',
        'SK': 'DETAILS'
    })
    order = response.get('Item')
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for('dashboard'))
    for item in order.get('items', []):
        product_id = item['product_id']
        appdata_table.put_item(Item={
            'PK': f'RATING#{product_id}',
            'SK': f'USER#{user_id}',
            'product_id': product_id,
            'user_id': user_id,
            'rating': rating,
            'timestamp': datetime.now().isoformat()
        })
    flash("Thank you for your rating!", "success")
    return redirect(url_for('dashboard'))

@app.route('/services')
def services():
    return render_template('services.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
