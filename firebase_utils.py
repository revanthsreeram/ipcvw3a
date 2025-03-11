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
            # Use the credentials from streamlit secrets
            cred_dict = st.secrets["firebase"]
            cred = credentials.Certificate(cred_dict)
            project_id = cred_dict.get("project_id", "fingerprint-matcher")
            storage_bucket = f"{project_id}.firebasestorage.app"
            print(f"Using Firebase credentials from Streamlit secrets")
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
    
    return db, bucket

# Rest of your firebase_utils.py file remains the same
# ...