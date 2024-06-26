# ui_elements.py
import streamlit as st
import pandas as pd
from datetime import datetime
import json
import os
import ollama
from ollama_utils import *
from model_tests import *
import requests
import re
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import CharacterTextSplitter
from langchain.docstore.document import Document
from prompts import get_agent_prompt, get_metacognitive_prompt, manage_prompts
from web_to_corpus import WebsiteCrawler
import shutil
import tiktoken
from chat_interface import chat_interface  # Import the chat_interface function

def list_local_models():
    response = requests.get(f"{OLLAMA_URL}/tags")
    response.raise_for_status()
    models = response.json().get("models", [])
    if not models:
        st.write("No local models available.")
        return
    
    # Prepare data for the dataframe
    data = []
    for model in models:
        size_gb = model.get('size', 0) / (1024**3)  # Convert bytes to GB
        modified_at = model.get('modified_at', 'Unknown')
        if modified_at != 'Unknown':
            modified_at = datetime.fromisoformat(modified_at).strftime('%Y-%m-%d %H:%M:%S')
        data.append({
            "Model Name": model['name'],
            "Size (GB)": size_gb,
            "Modified At": modified_at
        })
    
    # Create a pandas dataframe
    df = pd.DataFrame(data)

    # Calculate height based on the number of rows
    row_height = 35  # Set row height
    height = row_height * len(df) + 35  # Calculate height
    
    # Display the dataframe with Streamlit
    st.dataframe(df, use_container_width=True, height=height, hide_index=True)

def update_model_selection(selected_models, key):
    """Callback function to update session state during form submission."""
    st.session_state[key] = selected_models

@st.cache_data  # Cache the comparison and visualization logic
def run_comparison(selected_models, prompt, temperature, max_tokens, presence_penalty, frequency_penalty):
    results = performance_test(selected_models, prompt, temperature, max_tokens, presence_penalty, frequency_penalty)

    # Prepare data for visualization
    models = list(results.keys())  # Get models from results
    times = [results[model][1] for model in models]
    tokens_per_second = [
        results[model][2] / (results[model][3] / (10**9)) if results[model][2] and results[model][3] else 0
        for model in models
    ]

    df = pd.DataFrame({"Model": models, "Time (seconds)": times, "Tokens/second": tokens_per_second})

    return results, df, tokens_per_second, models  # Return models

def model_comparison_test():
    st.header("Model Comparison by Response Quality")

    # Refresh available_models list
    available_models = get_available_models()

    # Initialize selected_models in session state if it doesn't exist
    if "selected_models" not in st.session_state:
        st.session_state.selected_models = []

    # Pass the session state variable as the default for st.multiselect
    selected_models = st.multiselect(
        "Select the models you want to compare:",
        available_models,
        default=st.session_state.selected_models,  # Use session state for default
        key="model_comparison_models"  # Unique key for this multiselect
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.5, step=0.1)
    with col2:
        max_tokens = st.slider("Max Tokens", min_value=100, max_value=32000, value=4000, step=100)
    with col3:
        presence_penalty = st.slider("Presence Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)
    with col4:
        frequency_penalty = st.slider("Frequency Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)

    prompt = st.text_area("Enter the prompt:", value="Write a short story about a brave knight.")

    # Check if the button is clicked
    if st.button(label='Compare Models'):
        if selected_models:
            # Run the comparison and get the results, dataframe, tokens_per_second, and models
            results, df, tokens_per_second, models = run_comparison(selected_models, prompt, temperature, max_tokens, presence_penalty, frequency_penalty)

            # Plot the results using st.bar_chart
            st.bar_chart(df, x="Model", y=["Time (seconds)", "Tokens/second"], color=["#4CAF50", "#FFC107"])  # Green and amber

            for model, (result, elapsed_time, eval_count, eval_duration) in results.items():
                st.subheader(f"Results for {model} (Time taken: {elapsed_time:.2f} seconds, Tokens/second: {tokens_per_second[models.index(model)]:.2f}):")
                st.write(result)
                st.write("📦 JSON Handling Capability: ", "✅" if check_json_handling(model, temperature, max_tokens, presence_penalty, frequency_penalty) else "❌")
                st.write("⚙️ Function Calling Capability: ", "✅" if check_function_calling(model, temperature, max_tokens, presence_penalty, frequency_penalty) else "❌")
        else:
            st.warning("Please select at least one model.")

def vision_comparison_test():
    st.header("Vision Model Comparison")

    # Refresh available_models list
    available_models = get_available_models()

    # Initialize selected_vision_models in session state if it doesn't exist
    if "selected_vision_models" not in st.session_state:
        st.session_state.selected_vision_models = []

    # Pass the session state variable as the default for st.multiselect
    selected_models = st.multiselect(
        "Select the models you want to compare:",
        available_models,
        default=st.session_state.selected_vision_models,  # Use session state for default
        key="vision_comparison_models"  # Unique key for this multiselect
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.5, step=0.1)
    with col2:
        max_tokens = st.slider("Max Tokens", min_value=100, max_value=32000, value=4000, step=100)
    with col3:
        presence_penalty = st.slider("Presence Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)
    with col4:
        frequency_penalty = st.slider("Frequency Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)

    uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "png"])

    # Check if the button is clicked
    if st.button(label='Compare Vision Models'):
        if uploaded_file is not None:
            if selected_models:
                # Display the uploaded image
                st.image(uploaded_file, caption="Uploaded Image", use_column_width=True)

                results = {}
                for model in selected_models:
                    # Reset file pointer to the beginning
                    uploaded_file.seek(0)

                    start_time = time.time()
                    try:
                        # Use ollama.chat for vision tests
                        response = ollama.chat(
                            model=model,
                            messages=[
                                {
                                    'role': 'user',
                                    'content': 'Describe this image:',
                                    'images': [uploaded_file]
                                }
                            ]
                        )
                        result = response['message']['content']
                        print(f"Model: {model}, Result: {result}")  # Debug statement
                    except Exception as e:
                        result = f"An error occurred: {str(e)}"
                    end_time = time.time()
                    elapsed_time = end_time - start_time
                    results[model] = (result, elapsed_time)
                    time.sleep(0.1)

                # Display the LLM response text and time taken
                for model, (result, elapsed_time) in results.items():
                    st.subheader(f"Results for {model} (Time taken: {elapsed_time:.2f} seconds):")
                    st.write(result)

                # Prepare data for visualization (after displaying responses)
                models = list(results.keys())
                times = [results[model][1] for model in models]
                df = pd.DataFrame({"Model": models, "Time (seconds)": times})

                # Plot the results
                st.bar_chart(df, x="Model", y="Time (seconds)", color="#4CAF50")
            else:
                st.warning("Please select at least one model.")
        else:
            st.warning("Please upload an image.")

def contextual_response_test():
    st.header("Contextual Response Test by Model")

    # Refresh available_models list
    available_models = get_available_models()

    # Initialize selected_model in session state if it doesn't exist
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = available_models[0] if available_models else None

    # Use a separate key for the selectbox
    selectbox_key = "contextual_test_model_selector"

    # Update selected_model when selectbox changes
    if selectbox_key in st.session_state:
        st.session_state.selected_model = st.session_state[selectbox_key]

    selected_model = st.selectbox(
        "Select the model you want to test:", 
        available_models, 
        key=selectbox_key,
        index=available_models.index(st.session_state.selected_model) if st.session_state.selected_model in available_models else 0
    )

    prompts = st.text_area("Enter the prompts (one per line):", value="Hi, how are you?\nWhat's your name?\nTell me a joke.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.5, step=0.1)
    with col2:
        max_tokens = st.slider("Max Tokens", min_value=100, max_value=32000, value=4000, step=100)
    with col3:
        presence_penalty = st.slider("Presence Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)
    with col4:
        frequency_penalty = st.slider("Frequency Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)

    if st.button("Start Contextual Test", key="start_contextual_test"):
        prompt_list = [p.strip() for p in prompts.split("\n")]
        context = []
        times = []
        tokens_per_second_list = []
        for i, prompt in enumerate(prompt_list):
            start_time = time.time()
            result, context, eval_count, eval_duration = call_ollama_endpoint(
                selected_model,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                presence_penalty=presence_penalty,
                frequency_penalty=frequency_penalty,
                context=context,
            )
            end_time = time.time()
            elapsed_time = end_time - start_time
            times.append(elapsed_time)
            tokens_per_second = eval_count / (eval_duration / (10**9)) if eval_count and eval_duration else 0
            tokens_per_second_list.append(tokens_per_second)
            st.subheader(f"Prompt {i+1}: {prompt} (Time taken: {elapsed_time:.2f} seconds, Tokens/second: {tokens_per_second:.2f}):")
            st.write(f"Response: {result}")

        # Prepare data for visualization
        data = {"Prompt": prompt_list, "Time (seconds)": times, "Tokens/second": tokens_per_second_list}
        df = pd.DataFrame(data)

        # Plot the results using st.bar_chart
        st.bar_chart(df, x="Prompt", y=["Time (seconds)", "Tokens/second"], color=["#4CAF50", "#FFC107"])  # Green and amber

        st.write("📦 JSON Handling Capability: ", "✅" if check_json_handling(selected_model, temperature, max_tokens, presence_penalty, frequency_penalty) else "❌")
        st.write("⚙️ Function Calling Capability: ", "✅" if check_function_calling(selected_model, temperature, max_tokens, presence_penalty, frequency_penalty) else "❌")

def feature_test():
    st.header("Model Feature Test")
    
    # Refresh available_models list
    available_models = get_available_models()

    # Initialize selected_model in session state if it doesn't exist
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = available_models[0] if available_models else None

    # Use a separate key for the selectbox
    selectbox_key = "feature_test_model_selector"

    # Update selected_model when selectbox changes
    if selectbox_key in st.session_state:
        st.session_state.selected_model = st.session_state[selectbox_key]

    selected_model = st.selectbox(
        "Select the model you want to test:", 
        available_models, 
        key=selectbox_key,
        index=available_models.index(st.session_state.selected_model) if st.session_state.selected_model in available_models else 0
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.5, step=0.1)
    with col2:
        max_tokens = st.slider("Max Tokens", min_value=100, max_value=32000, value=4000, step=100)
    with col3:
        presence_penalty = st.slider("Presence Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)
    with col4:
        frequency_penalty = st.slider("Frequency Penalty", min_value=-2.0, max_value=2.0, value=0.0, step=0.1)

    if st.button("Run Feature Test", key="run_feature_test"):
        json_result = check_json_handling(selected_model, temperature, max_tokens, presence_penalty, frequency_penalty)
        function_result = check_function_calling(selected_model, temperature, max_tokens, presence_penalty, frequency_penalty)

        st.markdown(f"### 📦 JSON Handling Capability: {'✅ Success!' if json_result else '❌ Failure!'}")
        st.markdown(f"### ⚙️ Function Calling Capability: {'✅ Success!' if function_result else '❌ Failure!'}")


def list_models():
    st.header("List Local Models")
    models = list_local_models()
    if models:
        # Prepare data for the dataframe
        data = []
        for model in models:
            size_gb = model.get('size', 0) / (1024**3)  # Convert bytes to GB
            modified_at = model.get('modified_at', 'Unknown')
            if modified_at != 'Unknown':
                modified_at = datetime.fromisoformat(modified_at).strftime('%Y-%m-%d %H:%M:%S')
            data.append({
                "Model Name": model['name'],
                "Size (GB)": size_gb,
                "Modified At": modified_at
            })
        
        # Create a pandas dataframe
        df = pd.DataFrame(data)

        # Calculate height based on the number of rows
        row_height = 35  # Set row height
        height = row_height * len(df) + 35  # Calculate height
        
        # Display the dataframe with Streamlit
        st.dataframe(df, use_container_width=True, height=height, hide_index=True)

def pull_models():
    st.header("Pull a Model from Ollama Library")
    st.write("Enter the exact name of the model you want to pull from the Ollama library. You can just paste the whole model snippet from the model library page like 'ollama run llava-phi3' or you can just enter the model name like 'llava-phi3' and then click 'Pull Model' to begin the download. The progress of the download will be displayed below.")
    model_name = st.text_input("Enter the name of the model you want to pull:")
    if st.button("Pull Model", key="pull_model"):
        if model_name:
            # Strip off "ollama run" or "ollama pull" from the beginning
            model_name = model_name.replace("ollama run ", "").replace("ollama pull ", "").strip()

            result = pull_model(model_name)
            if any("error" in status for status in result):
                st.warning(f"Model '{model_name}' not found. Please make sure you've entered the correct model name. "
                           f"Model names often include a ':' to specify the variant. For example: 'mistral:instruct'")
            else:
                for status in result:
                    st.write(status)
        else:
            st.error("Please enter a model name.")

def show_model_details():
    st.header("Show Model Information")
    
    # Refresh available_models list
    available_models = get_available_models()

    # Initialize selected_model in session state if it doesn't exist
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = available_models[0] if available_models else None

    # Use a separate key for the selectbox
    selectbox_key = "show_model_details_model_selector"

    # Update selected_model when selectbox changes
    if selectbox_key in st.session_state:
        st.session_state.selected_model = st.session_state[selectbox_key]

    selected_model = st.selectbox(
        "Select the model you want to show details for:", 
        available_models, 
        key=selectbox_key,
        index=available_models.index(st.session_state.selected_model) if st.session_state.selected_model in available_models else 0
    )

    if st.button("Show Model Information", key="show_model_information"):
        details = show_model_info(selected_model)
        st.json(details)

def remove_model_ui():
    st.header("Remove a Model")
    
    # Refresh available_models list
    available_models = get_available_models()

    # Initialize selected_model in session state if it doesn't exist
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = available_models[0] if available_models else None

    # Use a separate key for the selectbox
    selectbox_key = "remove_model_ui_model_selector"

    # Update selected_model when selectbox changes
    if selectbox_key in st.session_state:
        st.session_state.selected_model = st.session_state[selectbox_key]

    selected_model = st.selectbox(
        "Select the model you want to remove:", 
        available_models, 
        key=selectbox_key,
        index=available_models.index(st.session_state.selected_model) if st.session_state.selected_model in available_models else 0
    )

    confirm_label = f"❌ Confirm removal of model `{selected_model}`"
    confirm = st.checkbox(confirm_label)
    if st.button("Remove Model", key="remove_model") and confirm:
        if selected_model:
            result = remove_model(selected_model)
            st.write(result["message"])

            # Clear the cache of get_available_models
            get_available_models.clear()

            # Update the list of available models
            st.session_state.available_models = get_available_models()
            # Update selected_model if it was removed
            if selected_model not in st.session_state.available_models:
                st.session_state.selected_model = st.session_state.available_models[0] if st.session_state.available_models else None
            st.rerun()
        else:
            st.error("Please select a model.")

def update_models():
    st.header("Update Local Models")
    available_models = get_available_models()
    if st.button("Update All Models"):
        for model_name in available_models:
            # Skip custom models (those with a ':' in the name)
            if 'gpt' in model_name:
                st.write(f"Skipping custom model: `{model_name}`")
                continue
            st.write(f"Updating model: `{model_name}`")
            pull_model(model_name)
        st.success("All models updated successfully!")

def count_tokens(text):
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

def files_tab():
    st.subheader("Files")
    files_folder = "files"
    if not os.path.exists(files_folder):
        os.makedirs(files_folder)
    allowed_extensions = ['.json', '.txt', '.pdf', '.gif', '.jpg', '.jpeg', '.png']
    files = [f for f in os.listdir(files_folder) if os.path.isfile(os.path.join(files_folder, f)) and os.path.splitext(f)[1].lower() in allowed_extensions]

    for file in files:
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            st.write(file)
        with col2:
            if file.endswith('.pdf'):
                st.button("📥", key=f"download_{file}")
            else:
                st.button("👁️", key=f"view_{file}")
        with col3:
            if not file.endswith('.pdf'):
                st.button("✏️", key=f"edit_{file}")
        with col4:
            st.button("🗑️", key=f"delete_{file}")

    for file in files:
        file_path = os.path.join(files_folder, file)
        
        if st.session_state.get(f"view_{file}", False):
            try:
                with open(file_path, "r", encoding='utf-8') as f:
                    file_content = f.read()
                st.text_area("File Content:", value=file_content, height=200, key=f"view_content_{file}")
            except UnicodeDecodeError:
                st.error(f"Unable to decode file {file}. It may be a binary file.")
        
        if st.session_state.get(f"edit_{file}", False):
            try:
                with open(file_path, "r", encoding='utf-8') as f:
                    file_content = f.read()
                new_content = st.text_area("Edit File Content:", value=file_content, height=200, key=f"edit_content_{file}")
                if st.button("Save Changes", key=f"save_{file}"):
                    with open(file_path, "w", encoding='utf-8') as f:
                        f.write(new_content)
                    st.success(f"Changes saved to {file}")
            except UnicodeDecodeError:
                st.error(f"Unable to decode file {file}. It may be a binary file.")
        
        if st.session_state.get(f"download_{file}", False):
            if file.endswith('.pdf'):
                with open(file_path, "rb") as pdf_file:
                    pdf_bytes = pdf_file.read()
                st.download_button(
                    label="Download PDF",
                    data=pdf_bytes,
                    file_name=file,
                    mime='application/pdf',
                )
            else:
                with open(file_path, "r", encoding='utf-8') as f:
                    file_content = f.read()
                st.download_button(
                    label="Download File",
                    data=file_content,
                    file_name=file,
                    mime='text/plain',
                )
        
        if st.session_state.get(f"delete_{file}", False):
            os.remove(file_path)
            st.success(f"File {file} deleted.")
            st.experimental_rerun()
    

   # File upload section
    uploaded_file = st.file_uploader("Upload a file", type=['txt', 'pdf', 'json', 'gif', 'jpg', 'jpeg', 'png'])
    if uploaded_file is not None:
        file_path = os.path.join(files_folder, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"File {uploaded_file.name} uploaded successfully!")
        st.experimental_rerun()

def extract_code_blocks(text):
    # Simple regex to extract code blocks (text between triple backticks)
    code_blocks = re.findall(r'```[\s\S]*?```', text)
    # Remove the backticks
    return [block.strip('`').strip() for block in code_blocks]

def get_corpus_context(corpus_file, query):
    # Load and split the corpus file
    files_folder = "files"
    if not os.path.exists(files_folder):
        os.makedirs(files_folder)
    try:
        with open(os.path.join(files_folder, corpus_file), "r", encoding='utf-8') as f:
            corpus_text = f.read()
    except UnicodeDecodeError:
        return "Error: Unable to decode the corpus file. Please ensure it's a text file."

    # Add progress bar for reading the corpus
    st.info(f"Reading corpus file: {corpus_file}")
    progress_bar = st.progress(0)
    total_chars = len(corpus_text)
    chars_processed = 0

    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    texts = []
    for chunk in text_splitter.split_text(corpus_text):
        texts.append(chunk)
        chars_processed += len(chunk)
        progress = chars_processed / total_chars
        progress_bar.progress(progress)

    # Create Langchain documents
    docs = [Document(page_content=t) for t in texts]

    # Create and load the vector database
    st.info("Creating vector database...")
    embeddings = OllamaEmbeddings()
    db = Chroma.from_documents(docs, embeddings, persist_directory="./chroma_db")
    db.persist()

    # Perform similarity search
    st.info("Performing similarity search...")
    results = db.similarity_search(query, k=3)
    st.info("Done!")
    return "\n".join([doc.page_content for doc in results])

def manage_corpus():
    st.header("Manage Corpus")

    # Corpus folder
    corpus_folder = "corpus"
    if not os.path.exists(corpus_folder):
        os.makedirs(corpus_folder)

    # List existing corpus
    corpus_list = [f for f in os.listdir(corpus_folder) if os.path.isdir(os.path.join(corpus_folder, f))]
    st.subheader("Existing Corpus")
    if corpus_list:
        for corpus in corpus_list:
            col1, col2, col3 = st.columns([2, 1, 1])  # Add a column for renaming
            with col1:
                st.write(corpus)
            with col2:
                if st.button("✏️", key=f"rename_corpus_{corpus}"):
                    st.session_state.rename_corpus = corpus
                    st.experimental_rerun()
            with col3:
                if st.button("🗑️", key=f"delete_corpus_{corpus}"):
                    shutil.rmtree(os.path.join(corpus_folder, corpus))
                    st.success(f"Corpus '{corpus}' deleted.")
                    st.experimental_rerun()
    else:
        st.write("No existing corpus found.")

    # Handle renaming corpus
    if "rename_corpus" in st.session_state and st.session_state.rename_corpus:
        corpus_to_rename = st.session_state.rename_corpus
        new_corpus_name = st.text_input(f"Rename corpus '{corpus_to_rename}' to:", value=corpus_to_rename, key=f"rename_corpus_input_{corpus_to_rename}")
        if st.button("Confirm Rename", key=f"confirm_rename_{corpus_to_rename}"):
            if new_corpus_name:
                os.rename(os.path.join(corpus_folder, corpus_to_rename), os.path.join(corpus_folder, new_corpus_name))
                st.success(f"Corpus renamed to '{new_corpus_name}'")
                st.session_state.rename_corpus = None
                st.experimental_rerun()
            else:
                st.error("Please enter a new corpus name.")

    st.subheader("Create New Corpus")
    # Create corpus from files
    st.write("**From Files:**")
    files_folder = "files"
    allowed_extensions = ['.json', '.txt']
    files = [f for f in os.listdir(files_folder) if os.path.isfile(os.path.join(files_folder, f)) and os.path.splitext(f)[1].lower() in allowed_extensions]
    selected_files = st.multiselect("Select files to create corpus:", files, key="create_corpus_files")
    corpus_name = st.text_input("Enter a name for the corpus:", key="create_corpus_name")
    if st.button("Create Corpus from Files", key="create_corpus_button"):
        if selected_files and corpus_name:
            create_corpus_from_files(corpus_folder, corpus_name, files_folder, selected_files)
            st.success(f"Corpus '{corpus_name}' created from selected files.")
            st.experimental_rerun()
        else:
            st.error("Please select files and enter a corpus name.")

def create_corpus_from_files(corpus_folder, corpus_name, files_folder, selected_files):
    corpus_path = os.path.join(corpus_folder, corpus_name)
    os.makedirs(corpus_path, exist_ok=True)
    
    # Combine all selected file content into one text
    all_text = ""
    for file in selected_files:
        file_path = os.path.join(files_folder, file)
        with open(file_path, "r", encoding='utf-8') as f:
            file_content = f.read()
        all_text += file_content + "\n\n"

    create_corpus_from_text(corpus_folder, corpus_name, all_text)

def create_corpus_from_text(corpus_folder, corpus_name, corpus_text):
    corpus_path = os.path.join(corpus_folder, corpus_name)
    os.makedirs(corpus_path, exist_ok=True)

    # Create Langchain documents
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    texts = text_splitter.split_text(corpus_text)
    docs = [Document(page_content=t) for t in texts]

    # Create and load the vector database
    embeddings = OllamaEmbeddings()
    db = Chroma.from_documents(docs, embeddings, persist_directory=corpus_path)
    db.persist()

def get_corpus_context_from_db(corpus_folder, corpus_name, query):
    corpus_path = os.path.join(corpus_folder, corpus_name)
    embeddings = OllamaEmbeddings()
    db = Chroma(persist_directory=corpus_path, embedding_function=embeddings)
    results = db.similarity_search(query, k=3)
    return "\n".join([doc.page_content for doc in results])