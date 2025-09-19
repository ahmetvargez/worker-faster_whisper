from huggingface_hub import snapshot_download


def download_model_weights(selected_model):
    """
    Download model weights.
    """
    print(f"Downloading {selected_model}...")
    # model ID from the URL
    model_id = "Systran/faster-whisper-medium.en"
    # this will download the model to the cache dir (by default ~/.cache/huggingface)
    local_dir = snapshot_download(repo_id=model_id)

    print(f"Model downloaded to: {local_dir}")
