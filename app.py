import streamlit as st
import pandas as pd
import numpy as np
import os
import traceback
import base64
from io import BytesIO
import requests
from firebase_utils import initialize_firebase, match_minutiae_with_database

# Set up page configuration
st.set_page_config(
    page_title="IAFIS",
    page_icon="IAFISt.png",
    layout="centered"
)

# Initialize Firebase at startup
try:
    db, bucket = initialize_firebase()
    firebase_initialized = True
except Exception as e:
    st.error(f"Error initializing Firebase: {str(e)}")
    firebase_initialized = False
    st.write("Please check your serviceAccountKey.json file and Firebase setup.")

# Function to fetch and display image from URL
def display_image_from_url(image_url, caption=""):
    try:
        # Fetch the image data
        response = requests.get(image_url)
        if response.status_code == 200:
            # Get the image data and content type
            image_data = response.content
            
            # Display the image
            st.image(image_data, caption=caption, use_container_width=True)
            
            # Return the data for potential download
            return image_data
        else:
            st.warning(f"Failed to load image: HTTP {response.status_code}")
            return None
    except Exception as e:
        st.warning(f"Error loading image: {str(e)}")
        st.write(f"Image URL: {image_url}")
        return None

# Function to create a download link for images
def get_image_download_link(img_data, filename="fingerprint.jpg"):
    try:
        b64 = base64.b64encode(img_data).decode()
        href = f'<a href="data:image/jpeg;base64,{b64}" download="{filename}">Download Image</a>'
        return href
    except Exception as e:
        return f"Error creating download link: {str(e)}"

# Function to display match information
def display_match_info(match_data, similarity):
    # Display match confidence
    st.metric("Match Confidence", f"{similarity['score']:.2f}%")
    
    # Display matched points info
    st.write(f"Matched {similarity['matchedPoints']} out of {similarity['totalPoints']} minutiae points")
    
    # Display assignment data
    if "assignmentData" in match_data:
        st.subheader("Matched Person Data")
        assignment_data = match_data["assignmentData"].copy()
        
        # Remove image URL from display
        if 'suspectImageUrl' in assignment_data:
            del assignment_data['suspectImageUrl']
        
        # Display in a more user-friendly format
        cols = st.columns(2)
        if 'suspectId' in assignment_data:
            cols[1].metric("Citizen ID", assignment_data['suspectId'])
        if 'suspectName' in assignment_data:
            cols[0].metric("Citizen Name", assignment_data['suspectName'])
        
        # Display additional notes if any
        if 'additionalNotes' in assignment_data and assignment_data['additionalNotes']:
            st.write("**Additional Notes:**")
            st.write(assignment_data['additionalNotes'])
    
    # Check if there's an image URL
    if (match_data.get('assignmentData', {}) and 'suspectImageUrl' in match_data['assignmentData']):
        image_url = match_data['assignmentData']['suspectImageUrl']
        
        # Display the image
        st.subheader("Suspect Image")
        img_data = display_image_from_url(image_url, "Suspect Image")
        
        # Add download button if image was loaded
        if img_data:
            suspect_id = match_data['assignmentData'].get('suspectId', 'suspect')
            # Get file extension from URL, default to jpg
            file_ext = os.path.splitext(image_url)[1]
            if not file_ext:
                file_ext = ".jpg"
            download_link = get_image_download_link(img_data, f"{suspect_id}{file_ext}")
            st.markdown(download_link, unsafe_allow_html=True)
    
    

# App title and description
left_co,cent_co,last_co = st.columns(3)
with cent_co:
    st.image("IAFISt.png",width=210,)
st.markdown("<h1 style='text-align: center; color: grey;'>Integrated Automated Fingerprint Identification System</h1>", unsafe_allow_html=True)
st.title("Integrated Automated Fingerprint Identification System")
st.subheader("Federal Bureau of Investigation")
st.subheader("Image Processing and Computer Vision Worksheet 3A Criminal Database")
st.markdown("""
Upload your CSV file containing fingerprint minutiae features to find a match in the criminal database.
The CSV should contain columns for x-coordinate, y-coordinate, type, and angle (without headers).
""")

# File uploader
uploaded_file = st.file_uploader("Upload your minutiae CSV file", type=["csv"])

if uploaded_file is not None:
    # Display the uploaded file as a dataframe
    try:
        # Explicitly set header=None to indicate there are no headers in the CSV
        df = pd.read_csv(uploaded_file, header=None)
        
        # Show preview
        st.write("Preview of uploaded data:")
        st.dataframe(df.head())
        
        # Match the minutiae with the database
        if st.button("Find Match"):
            if not firebase_initialized:
                st.error("Cannot match data because Firebase is not initialized.")
            else:
                with st.spinner("Matching fingerprint..."):
                    try:
                        # Try to match with database
                        result = match_minutiae_with_database(df)
                        
                        if result and 'match' in result and result['match']:
                            # Check if we have multiple perfect matches
                            if 'perfectMatches' in result and len(result['perfectMatches']) > 1:
                                st.success(f"Found {len(result['perfectMatches'])} perfect matches!")
                                
                                # Create tabs for each perfect match
                                tabs = st.tabs([f"Match {i+1}: {m['matchData']['studentInfo']['id']}" 
                                               for i, m in enumerate(result['perfectMatches'])])
                                
                                # Display each match in its own tab
                                for i, (tab, match) in enumerate(zip(tabs, result['perfectMatches'])):
                                    with tab:
                                        display_match_info(match['matchData'], match['similarity'])
                                
                                # Add debug info if requested
                                if st.checkbox("Show match details"):
                                    st.write("### Match Details")
                                    for i, match in enumerate(result['perfectMatches']):
                                        st.write(f"**Match {i+1}**: {match['id']}")
                                        st.write(f"Score: {match['similarity']['score']:.2f}%")
                                        st.write(f"Matched Points: {match['similarity']['matchedPoints']}/{match['similarity']['totalPoints']}")
                                    
                            else:
                                # Single match case
                                st.success("Match found!")
                                display_match_info(result['match'], result['similarity'])
                        
                        elif result and 'goodMatches' in result and result['goodMatches']:
                            # Show good matches
                            st.success(f"Found {len(result['goodMatches'])} good matches!")
                            
                            # Create tabs for each good match
                            tabs = st.tabs([f"Match {i+1}: {m['matchData']['studentInfo']['id']}" 
                                           for i, m in enumerate(result['goodMatches'])])
                            
                            # Display each match in its own tab
                            for i, (tab, match) in enumerate(zip(tabs, result['goodMatches'])):
                                with tab:
                                    display_match_info(match['matchData'], match['similarity'])
                        
                        elif result and 'closestMatch' in result:
                            # Show closest match that's below threshold
                            closest = result['closestMatch']
                            
                            st.warning("No exact match found, but here's the closest one:")
                            st.metric("Match Confidence", f"{closest['similarity']['score']:.2f}%")
                            st.write(f"Matched {closest['similarity']['matchedPoints']} out of {closest['similarity']['totalPoints']} minutiae points")
                            
                            # Show match details
                            display_match_info(closest['matchData'], closest['similarity'])
                        else:
                            st.error("No match found. Please check your data and try again.")
                    
                    except Exception as e:
                        st.error(f"Error during matching: {str(e)}")
                        st.write("Please try again or contact your instructor for assistance.")
                        
                        # Show detailed error in debug mode
                        if st.checkbox("Show detailed error"):
                            st.code(traceback.format_exc())
    
    except Exception as e:
        st.error(f"Error reading file: {str(e)}")
        st.write("Please make sure your CSV file is properly formatted.")

# Footer
st.markdown("---")
st.markdown("© Image Processing and Computer Vision Course 2025")
