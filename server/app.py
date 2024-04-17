from flask import request, jsonify, current_app, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime
import os
from config import app, db, UPLOAD_FOLDER
from models import User, Item, Favorites, UserFeedback
from sqlalchemy.exc import SQLAlchemyError

# Helper function for user authentication
def authenticate_user(email, password):
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password_hash, password):
        return user
    return None

# New configurations for file uploads
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"message": "Email already registered"}), 400
    
    new_user = User(email=data['email'], username=data['username'],
                    password_hash=generate_password_hash(data['password']))
    db.session.add(new_user)
    db.session.commit()

    # Create an access token for the new user
    access_token = create_access_token(identity=new_user.id)
    
    return jsonify({"message": "Registration successful", "user_id": new_user.id, "access_token": access_token}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = authenticate_user(data['email'], data['password'])
    if not user:
        return jsonify({"message": "Invalid credentials"}), 401
    access_token = create_access_token(identity=user.id)
    return jsonify({"message": "Login successful", "access_token": access_token}), 200

@app.route('/items', methods=['POST', 'GET'])
@jwt_required(optional=True)
def items():
    if request.method == 'POST':
        user_id = get_jwt_identity()
        if not user_id:
            return jsonify({"message": "Unauthorized"}), 401

        if 'image' not in request.files:
            return jsonify({"message": "No file part"}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({"message": "No selected file"}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        data = request.form
        time_to_be_set_on_curb = datetime.strptime(data['time_to_be_set_on_curb'], '%Y-%m-%dT%H:%M')

        new_item = Item(
            name=data['name'],
            description=data['description'],
            location=data['location'],
            condition=data['condition'],
            user_id=user_id,
            time_to_be_set_on_curb=time_to_be_set_on_curb,
            image=filename
        )
        db.session.add(new_item)
        db.session.commit()
        return jsonify({"message": "Item posted successfully", "item_id": new_item.id}), 201

    else:
        user_id = get_jwt_identity()
        posted_by_user = request.args.get('posted_by_user', 'false').lower() == 'true'
        
        if posted_by_user and user_id:
            # Fetch only items posted by the logged-in user
            items = Item.query.filter_by(user_id=user_id).all()
        else:
            # Fetch all items
            items = Item.query.all()
        
        items_data = []
        for item in items:
            item_dict = item.to_dict()
            item_dict['likes'] = UserFeedback.query.filter_by(item_id=item.id, feedback_type='LIKE').count()
            item_dict['dislikes'] = UserFeedback.query.filter_by(item_id=item.id, feedback_type='DISLIKE').count()
            item_dict['user_liked'] = UserFeedback.query.filter_by(item_id=item.id, user_id=user_id, feedback_type='LIKE').first() is not None
            item_dict['user_disliked'] = UserFeedback.query.filter_by(item_id=item.id, user_id=user_id, feedback_type='DISLIKE').first() is not None
            items_data.append(item_dict)
        return jsonify(items_data), 200

@app.route('/favorites', methods=['POST'])
@jwt_required()
def add_favorite():
    user_id = get_jwt_identity()
    data = request.json
    new_favorite = Favorites(user_id=user_id, item_id=data['item_id'])
    db.session.add(new_favorite)
    db.session.commit()
    return jsonify({"message": "Item added to favorites"}), 201

@app.route('/auth/user', methods=['GET'])
@jwt_required()
def get_current_user_profile():
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)
    return jsonify({
        "id": user.id,
        "email": user.email,
        "username": user.username
    }), 200

@app.route('/users/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_profile(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify({
        "id": user.id,
        "email": user.email,
        "username": user.username
    }), 200

@app.route('/items/<int:item_id>', methods=['GET'])
@jwt_required(optional=True)
def get_item(item_id):
    user_id = get_jwt_identity()
    item = Item.query.get_or_404(item_id)
    item_dict = item.to_dict()
    # Add feedback counts and user feedback status
    item_dict['likes'] = UserFeedback.query.filter_by(item_id=item.id, feedback_type='LIKE').count()
    item_dict['dislikes'] = UserFeedback.query.filter_by(item_id=item.id, feedback_type='DISLIKE').count()
    item_dict['user_liked'] = UserFeedback.query.filter_by(item_id=item.id, user_id=user_id, feedback_type='LIKE').first() is not None
    item_dict['user_disliked'] = UserFeedback.query.filter_by(item_id=item.id, user_id=user_id, feedback_type='DISLIKE').first() is not None
    return jsonify(item_dict), 200

@app.route('/items/<int:item_id>', methods=['PUT'])
@jwt_required()
def update_item(item_id):
    item = Item.query.get_or_404(item_id)
    if item.user_id != get_jwt_identity():
        return jsonify({"message": "Unauthorized"}), 403

    data = request.form
    if 'image' in request.files:  # Adjusted to 'image' to match the POST route
        file = request.files['image']
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        item.image = filename  # Only store the filename

    # Check and update each field only if it has been provided in the form data
    if 'name' in data:
        item.name = data['name']
    if 'description' in data:
        item.description = data['description']
    if 'location' in data:
        item.location = data['location']
    if 'condition' in data:
        item.condition = data['condition']
    if 'time_to_be_set_on_curb' in data:
        try:
            item.time_to_be_set_on_curb = datetime.strptime(data['time_to_be_set_on_curb'], '%Y-%m-%dT%H:%M')
        except ValueError:
            return jsonify({"message": "Invalid date format. Please use YYYY-MM-DDTHH:MM."}), 400

    db.session.commit()
    updated_item = Item.query.get(item_id)
    return jsonify({"message": "Item updated successfully", "item": updated_item.to_dict()}), 200

@app.route('/items/<int:item_id>', methods=['DELETE'])
@jwt_required()
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    if item.user_id != get_jwt_identity():
        return jsonify({"message": "Unauthorized"}), 403

    try:
        # Delete all associated favorites and feedbacks
        Favorites.query.filter_by(item_id=item_id).delete()
        UserFeedback.query.filter_by(item_id=item_id).delete()

        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Item deleted successfully"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Database error during deletion: {e}")
        return jsonify({"message": "Failed to delete item", "error": str(e)}), 500

@app.route('/items/<int:item_id>', methods=['PATCH'])
@jwt_required()
def patch_item(item_id):
    item = Item.query.get_or_404(item_id)
    if item.user_id != get_jwt_identity():
        return jsonify({"message": "Unauthorized"}), 403

    data = request.get_json()
    print("Received PATCH data:", data)

    try:
        if 'name' in data:
            item.name = data['name']
        if 'description' in data:
            item.description = data['description']
        if 'location' in data:
            item.location = data['location']
        if 'condition' in data:
            item.condition = data['condition']
        if 'time_to_be_set_on_curb' in data and data['time_to_be_set_on_curb']:
            item.time_to_be_set_on_curb = datetime.strptime(data['time_to_be_set_on_curb'], '%Y-%m-%d %H:%M:%S')

        db.session.commit()
        return jsonify({"message": "Item updated successfully", "item": item.to_dict()}), 200

    except ValueError as ve:
        print(f"Value error: {ve}")
        return jsonify({"message": "Invalid date format. Please use YYYY-MM-DD HH:MM:SS.", "error": str(ve)}), 400
    except SQLAlchemyError as sae:
        db.session.rollback()
        print(f"Database error: {sae}")
        return jsonify({"message": "Database error", "error": str(sae)}), 500
    except Exception as e:
        db.session.rollback()
        print(f"Unexpected error: {e}")
        return jsonify({"message": "An unexpected error occurred", "error": str(e)}), 500

@app.route('/favorites', methods=['GET'])
@jwt_required()
def get_favorites():
    user_id = get_jwt_identity()
    favorites = Favorites.query.filter_by(user_id=user_id).all()
    favorite_items = [favorite.item.to_dict() for favorite in favorites]  # Ensure my models have a to_dict method
    return jsonify(favorite_items), 200

@app.route('/favorites/<int:item_id>', methods=['POST'])
@jwt_required()
def add_to_favorites(item_id):
    user_id = get_jwt_identity()
    # Check if the item exists
    item = Item.query.get(item_id)
    if not item:
        return jsonify({"message": "Item not found"}), 404

    # Check if the item is already in favorites
    if Favorites.query.filter_by(user_id=user_id, item_id=item_id).first():
        return jsonify({"message": "Item already in favorites"}), 409
    
    # If the item exists and is not in favorites, add it
    favorite = Favorites(user_id=user_id, item_id=item_id)
    db.session.add(favorite)
    db.session.commit()
    return jsonify({"message": "Item added to favorites"}), 201

@app.route('/favorites/<int:item_id>', methods=['DELETE'])
@jwt_required()
def remove_from_favorites(item_id):
    user_id = get_jwt_identity()
    favorite = Favorites.query.filter_by(user_id=user_id, item_id=item_id).first()
    if not favorite:
        return jsonify({"message": "Item not found in favorites"}), 404
    
    db.session.delete(favorite)
    db.session.commit()
    return jsonify({"message": "Item removed from favorites"}), 200


@app.route('/feedback', methods=['POST'])
@jwt_required()
def submit_feedback():
    user_id = get_jwt_identity()
    data = request.json
    feedback_type = data.get('feedback_type')

    # Validate feedback_type
    if feedback_type not in ['LIKE', 'DISLIKE']:
        return jsonify({"message": "Invalid feedback type. Only 'LIKE' or 'DISLIKE' are accepted."}), 400

    # Proceed if feedback_type is valid
    feedback = UserFeedback(
        item_id=data['item_id'],
        user_id=user_id,
        feedback_type=feedback_type  # 'LIKE' or 'DISLIKE'
    )
    db.session.add(feedback)
    db.session.commit()

    # Return the feedback ID along with the success message
    return jsonify({"message": "Feedback submitted successfully", "feedback_id": feedback.id}), 201

@app.route('/items/<int:item_id>/feedback', methods=['GET'])
def get_feedback(item_id):
    feedbacks = UserFeedback.query.filter_by(item_id=item_id).all()
    feedback_data = [{"user_id": feedback.user_id, "feedback_type": feedback.feedback_type} for feedback in feedbacks]
    return jsonify(feedback_data), 200

@app.route('/feedback/<int:feedback_id>', methods=['DELETE'])
@jwt_required()
def delete_feedback(feedback_id):
    feedback = UserFeedback.query.get_or_404(feedback_id)
    if feedback.user_id != get_jwt_identity():
        return jsonify({"message": "Unauthorized"}), 403
    db.session.delete(feedback)
    db.session.commit()
    return jsonify({"message": "Feedback deleted successfully"}), 200

# Serving uploaded files 
@app.route('/upload', methods=['POST'])
@jwt_required()  
def upload_file():
    # New file upload handling code
    if 'file' not in request.files:
        return jsonify({"message": "No file part"}), 400
    file = request.files['file']
    filename = secure_filename(file.filename)
    if filename == '':
        return jsonify({"message": "No selected file"}), 400
    if file and allowed_file(filename):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return jsonify({"message": "File uploaded successfully", "filepath": file_path}), 201
    else:
        return jsonify({"message": "File type not allowed"}), 400

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS   

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        abort(404, description="Resource not found")

if __name__ == '__main__':
    app.run(debug=True, port=5555)

