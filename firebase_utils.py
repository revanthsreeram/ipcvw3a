import firebase_admin
from firebase_admin import credentials, firestore, storage as admin_storage
import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
import uuid
import tempfile
import streamlit as st

# Global variables
db = None
bucket = None

def initialize_firebase():
    """Initialize Firebase with service account credentials"""
    global db, bucket
    
    # If Firebase is already initialized, get the existing app and clients
    if firebase_admin._apps:
        try:
            # Get the default app if it exists
            app = firebase_admin.get_app()
            # Create clients if they don't exist
            if db is None:
                db = firestore.client(app=app, database_id="fingerprint-data")
            if bucket is None:
                bucket = admin_storage.bucket(app=app)
            print("Using existing Firebase app")
            return db, bucket
        except ValueError:
            # App doesn't exist (should not happen here, but just in case)
            pass
    
    # If not initialized yet, create a new app
    try:
        # Check if running on Streamlit Cloud (look for secrets)
        if hasattr(st, "secrets") and "firebase" in st.secrets:
            # Create a temporary JSON file with the secret credentials
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp:
                # Write the credentials to the temp file
                cred_dict = dict(st.secrets["firebase"])
    
                # Make sure private_key is properly formatted
                if "private_key" in cred_dict and isinstance(cred_dict["private_key"], str):
                    # Ensure the private key has proper newline characters
                    cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
    
                json.dump(cred_dict, temp)
                temp_path = temp.name
            
            # Use the temporary file for Firebase initialization
            cred = credentials.Certificate(temp_path)
            project_id = cred_dict.get("project_id", "fingerprint-matcher")
            storage_bucket = f"{project_id}.firebasestorage.app"
            
            print(f"Using Firebase credentials from Streamlit secrets")
            
            # Initialize Firebase
            app = firebase_admin.initialize_app(cred, {
                'projectId': project_id,
                'storageBucket': storage_bucket
            })
            
            # Delete the temporary file
            os.unlink(temp_path)
            
        else:
            # Use local credentials file
            service_account_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'serviceAccountKey.json')
            
            # Check if the service account file exists
            if not os.path.exists(service_account_path):
                raise FileNotFoundError(f"Firebase service account file not found at: {service_account_path}")
            
            cred = credentials.Certificate(service_account_path)
            project_id = "fingerprint-matcher"
            storage_bucket = "fingerprint-matcher.firebasestorage.app"
            
            print(f"Using Firebase credentials from local file: {service_account_path}")
            
            # Initialize Firebase
            app = firebase_admin.initialize_app(cred, {
                'projectId': project_id,
                'storageBucket': storage_bucket
            })
        
        db = firestore.client(app=app, database_id="fingerprint-data")
        bucket = admin_storage.bucket(app=app)
        
        print("Firebase successfully initialized")
    except ValueError as e:
        # App already exists, handle gracefully
        if "already exists" in str(e):
            app = firebase_admin.get_app()
            db = firestore.client(app=app, database_id="fingerprint-data")
            bucket = admin_storage.bucket(app=app)
            print("Using existing Firebase app")
        else:
            raise e
    except Exception as e:
        # Print detailed error for debugging
        import traceback
        print(f"Error initializing Firebase: {e}")
        print(traceback.format_exc())
        raise
    
    return db, bucket

# Rest of your firebase_utils.py code remains the same
# ...

def get_db_and_bucket():
    """Get the Firestore database and Storage bucket clients, initializing if necessary"""
    global db, bucket
    if db is None or bucket is None:
        db, bucket = initialize_firebase()
    return db, bucket

def upload_image_to_storage(image_file, fingerprint_id):
    """
    Upload an image to Firebase Storage
    
    Args:
        image_file: The image file to upload (StreamlitUploadedFile)
        fingerprint_id: ID to use for the image filename
        
    Returns:
        str: Public URL of the uploaded image
    """
    try:
        db, bucket = get_db_and_bucket()
        
        # Create a unique filename
        file_extension = os.path.splitext(image_file.name)[1].lower()
        storage_path = f"fingerprints/{fingerprint_id}{file_extension}"
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            # Write the uploaded file to the temporary file
            tmp_file.write(image_file.getvalue())
            tmp_file_path = tmp_file.name
        
        try:
            # Upload the file to Firebase Storage
            blob = bucket.blob(storage_path)
            blob.upload_from_filename(tmp_file_path)
            
            # Make the file publicly accessible
            blob.make_public()
            
            # Get the public URL
            image_url = blob.public_url
            
            print(f"Image uploaded successfully to {storage_path}")
            return image_url
        finally:
            # Clean up the temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
        
    except Exception as e:
        print(f"Error uploading image to storage: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def upload_to_firebase(reference_data, image_file=None):
    """
    Upload reference data and optionally an image to Firebase
    
    Args:
        reference_data (dict): Reference data to upload
        image_file: Optional image file to upload
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        db, bucket = get_db_and_bucket()
        
        # Generate a fingerprint ID if not provided
        if 'assignmentData' in reference_data and not reference_data['assignmentData'].get('fingerprintId'):
            fingerprint_id = f"FP{uuid.uuid4().hex[:8].upper()}"
            reference_data['assignmentData']['fingerprintId'] = fingerprint_id
        else:
            fingerprint_id = reference_data['assignmentData'].get('fingerprintId')
        
        # Upload image if provided
        if image_file is not None:
            image_url = upload_image_to_storage(image_file, fingerprint_id)
            if image_url:
                # Add image URL to reference data
                if 'assignmentData' not in reference_data:
                    reference_data['assignmentData'] = {}
                reference_data['assignmentData']['imageUrl'] = image_url
        
        # Add to the fingerprintReferences collection
        doc_ref = db.collection('fingerprintReferences').add(reference_data)
        
        print(f"Data uploaded successfully to fingerprintReferences collection")
        return True
    except Exception as e:
        print(f"Error uploading to Firebase: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def match_minutiae_with_database(minutiae_df):
    """
    Match the uploaded minutiae with reference data in the database
    
    Args:
        minutiae_df (pandas.DataFrame): DataFrame with minutiae data
        
    Returns:
        dict: Match result or None if no match found
    """
    try:
        db, bucket = get_db_and_bucket()
        
        # Try multiple column arrangements to find the best match
        all_matches = []
        
        # Different column arrangements to try
        arrangements = [
            # Default: x, y, type, angle
            {'x': 0, 'y': 1, 'type': 2, 'angle': 3},
            # x, y, angle, type
            {'x': 0, 'y': 1, 'angle': 2, 'type': 3},
            # type, x, y, angle
            {'type': 0, 'x': 1, 'y': 2, 'angle': 3},
            # angle, x, y, type
            {'angle': 0, 'x': 1, 'y': 2, 'type': 3}
        ]
        
        # Get all reference data from Firestore
        references = db.collection('fingerprintReferences').get()
        
        if not references:
            print("No references found in fingerprintReferences collection")
            return None
        
        # Prepare reference dataset
        reference_dataset = []
        for doc in references:
            data = doc.to_dict()
            if 'studentInfo' in data and 'id' in data['studentInfo']:
                srn = data['studentInfo']['id']
            else:
                srn = "Unknown"
                
            reference_dataset.append({
                'id': doc.id,
                'srn': srn,
                'minutiae': data.get('minutiae', []),
                'matchData': {
                    'studentInfo': data.get('studentInfo'),
                    'assignmentData': data.get('assignmentData')
                }
            })
        
        print(f"Found {len(reference_dataset)} reference fingerprints in database")
        
        # Process the uploaded minutiae in all formats
        all_test_minutiae = []
        for arrange in arrangements:
            # Map columns according to arrangement
            mapped_df = pd.DataFrame()
            for key, col_idx in arrange.items():
                if col_idx < len(minutiae_df.columns):
                    mapped_df[key] = minutiae_df.iloc[:, col_idx]
            
            # Convert to records
            test_minutiae = mapped_df.to_dict(orient='records')
            all_test_minutiae.append(test_minutiae)
        
        # For each reference, try all column arrangements
        for ref_data in reference_dataset:
            best_match_data = None
            best_match_score = 0
            
            for i, arrange in enumerate(arrangements):
                # Use the mapped minutiae for this arrangement
                test_minutiae = all_test_minutiae[i]
                
                # Try matching with this arrangement
                similarity = calculate_similarity(test_minutiae, ref_data['minutiae'], ref_data["srn"])
                
                # Update best match if better
                if similarity['score'] > best_match_score:
                    best_match_score = similarity['score']
                    best_match_data = {
                        'id': ref_data['id'],
                        'srn': ref_data['srn'],
                        'matchData': ref_data['matchData'],
                        'similarity': similarity,
                        'arrangement_used': i
                    }
            
            # Add best match for this reference to results
            if best_match_data:
                all_matches.append(best_match_data)
        
        # Sort all matches by score
        all_matches.sort(key=lambda x: x['similarity']['score'], reverse=True)
        
        # Find all near-perfect matches (100% or very close)
        threshold = 95  # Adjusted threshold based on test results
        perfect_threshold = 99  # Threshold for considering a match as "perfect"
        
        perfect_matches = [match for match in all_matches if match['similarity']['score'] >= perfect_threshold]
        good_matches = [match for match in all_matches if match['similarity']['score'] >= threshold and match['similarity']['score'] < perfect_threshold]
        
        # If we have any perfect matches, return all of them
        if perfect_matches:
            print(f"Found {len(perfect_matches)} perfect matches!")
            
            # Return all perfect matches and include top good matches as well
            return {
                'match': perfect_matches[0]['matchData'],  # Still use the top match as the primary
                'similarity': perfect_matches[0]['similarity'],
                'perfectMatches': perfect_matches,  # Include all perfect matches
                'goodMatches': good_matches[:3] if good_matches else [],  # Include up to 3 good matches
                'allMatches': all_matches[:5]  # Include top 5 matches for debugging
            }
        
        # Check for good matches if no perfect matches
        elif good_matches:
            print(f"Best match: ID {good_matches[0]['id']} with score {good_matches[0]['similarity']['score']:.2f}%")
            return {
                'match': good_matches[0]['matchData'],
                'similarity': good_matches[0]['similarity'],
                'goodMatches': good_matches,
                'allMatches': all_matches[:5]
            }
        else:
            if all_matches:
                print(f"Best match below threshold: ID {all_matches[0]['id']} with score {all_matches[0]['similarity']['score']:.2f}% (threshold: {threshold}%)")
                return {
                    'match': None,
                    'closestMatch': {
                        'id': all_matches[0]['id'],
                        'matchData': all_matches[0]['matchData'],
                        'similarity': all_matches[0]['similarity']
                    },
                    'allMatches': all_matches[:5]
                }
            else:
                print("No matches found at all")
                return None
    except Exception as e:
        print(f"Error matching minutiae with database: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def calculate_similarity(uploaded_minutiae, reference_minutiae, srn):
    """
    Calculate similarity between two minutiae datasets
    
    Args:
        uploaded_minutiae (list): List of dictionaries containing minutiae data
        reference_minutiae (list): List of dictionaries containing reference minutiae data
        srn: Student ID for logging purposes
        
    Returns:
        dict: Similarity score and match details
    """
    # Print summary
    print(f"Comparing {len(uploaded_minutiae)} uploaded points with {len(reference_minutiae)} reference points of student with srn {srn}")
    
    # Early check for empty sets
    if len(uploaded_minutiae) == 0 or len(reference_minutiae) == 0:
        return {
            'score': 0,
            'matchedPoints': 0,
            'totalPoints': max(len(uploaded_minutiae), len(reference_minutiae)),
            'matchDetails': []
        }
    
    # Convert all reference minutiae to use consistent keys
    normalized_reference = []
    for point in reference_minutiae:
        normalized_point = {}
        
        # Try different key formats
        if '0' in point:  # String numeric keys
            normalized_point['x'] = float(point.get('0', 0))
            normalized_point['y'] = float(point.get('1', 0))
            normalized_point['type'] = point.get('2', 0)
            normalized_point['angle'] = float(point.get('3', 0))
        elif 0 in point:  # Integer keys
            normalized_point['x'] = float(point.get(0, 0))
            normalized_point['y'] = float(point.get(1, 0))
            normalized_point['type'] = point.get(2, 0)
            normalized_point['angle'] = float(point.get(3, 0))
        else:  # Already has named keys
            normalized_point['x'] = float(point.get('x', 0))
            normalized_point['y'] = float(point.get('y', 0))
            normalized_point['type'] = point.get('type', 0)
            normalized_point['angle'] = float(point.get('angle', 0))
        
        normalized_reference.append(normalized_point)
    
    # Convert all uploaded minutiae to use consistent keys
    normalized_uploaded = []
    for point in uploaded_minutiae:
        normalized_point = {}
        
        # All uploads should have named keys already, but just in case
        normalized_point['x'] = float(point.get('x', 0))
        normalized_point['y'] = float(point.get('y', 0))
        normalized_point['type'] = point.get('type', 0)
        normalized_point['angle'] = float(point.get('angle', 0))
        
        normalized_uploaded.append(normalized_point)
    
    # Match points
    matches = 0
    match_details = []
    proximity_threshold = 5  # Distance threshold
    angle_threshold = 0.3    # Angle threshold in radians (about 17 degrees)
    
    for i, test_point in enumerate(normalized_uploaded):
        best_match_dist = float('inf')
        best_match_detail = None
        
        for j, ref_point in enumerate(normalized_reference):
            try:
                # Extract coordinates (already converted to float above)
                test_x = test_point['x']
                test_y = test_point['y']
                test_type = test_point['type']
                test_angle = test_point['angle']
                
                ref_x = ref_point['x']
                ref_y = ref_point['y']
                ref_type = ref_point['type']
                ref_angle = ref_point['angle']
                
                # Normalize types - convert strings to numbers if needed
                if isinstance(test_type, str) and test_type.isdigit():
                    test_type = int(test_type)
                if isinstance(ref_type, str) and ref_type.isdigit():
                    ref_type = int(ref_type)
                
                # Calculate distance
                distance = np.sqrt((test_x - ref_x)**2 + (test_y - ref_y)**2)
                
                # Calculate angle difference (handling circular nature)
                angle_diff = min(
                    abs(test_angle - ref_angle),
                    2 * np.pi - abs(test_angle - ref_angle)
                )
                
                # Type matching
                type_match = test_type == ref_type
                
                # Check if points match
                if distance <= proximity_threshold and angle_diff <= angle_threshold and type_match:
                    # Find the best (closest) match for this test point
                    if distance < best_match_dist:
                        best_match_dist = distance
                        best_match_detail = {
                            'test_idx': i,
                            'ref_idx': j,
                            'distance': float(distance),
                            'angle_diff': float(angle_diff),
                            'test_coords': (float(test_x), float(test_y)),
                            'ref_coords': (float(ref_x), float(ref_y))
                        }
            except Exception as e:
                print(f"Error comparing points {i} and {j}: {e}")
                continue
        
        # If we found a match for this test point, count it
        if best_match_detail:
            matches += 1
            match_details.append(best_match_detail)
    
    # Calculate similarity score
    total_points = max(len(normalized_uploaded), len(normalized_reference))
    similarity_score = (matches / total_points) * 100 if total_points > 0 else 0
    
    # Print results summary
    print(f"Matches found: {matches}/{total_points} = {similarity_score:.2f}%")
    
    return {
        'score': similarity_score,
        'matchedPoints': matches,
        'totalPoints': total_points,
        'matchDetails': match_details[:10] if match_details else []  # Include first 10 match details for debugging
    }
