# Vio-Movie — Inkaka The Guru

Local Flask production workspace with asset library, Character Bible, episodes, shots and Video AI Studio.

## Run on Windows

Open a terminal in `E:\Vio-Movie` using your existing Python environment:

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Only copy `.env.example` if you do not already have `.env`. Open http://127.0.0.1:5000/studio.
Keep this app local; it has no multi-user authentication.

## Prepare without paying

1. Save characters, episodes and scenes; generate and review a shot list.
2. In Video AI Studio choose the episode, shot and **Demo** provider.
3. Review the prompt, reference, duration, ratio and resolution; create a demo take.
4. Refresh twice to move from queued → running → demo ready. No provider requests or footage are created.
5. Optionally import an existing MP4 into a demo take, preview it, approve it and download it for Premiere.
6. Use **Prepare another take** to review and submit a separate attempt. No automatic paid retries occur.

Each take snapshots its original shot, prompt and settings. Changing or regenerating a shot list does not change old takes. Take associations use episode ID and shot number: finish shot ordering before production. If you regenerate/reorder a list later, consult the snapshot rather than assuming old takes match the new numbered shots.

## Enable Seedance when ready

Edit your local `.env`:

```dotenv
BYTEPLUS_API_KEY=your_private_key_here
BYTEPLUS_VIDEO_MODEL=your_activated_model_or_endpoint_id
VIDEO_LIVE_ENABLED=true
```

Restart the app, select Seedance and explicitly check the paid-generation acknowledgement for each take. Key presence is a configuration check, not proof of account credit or model access. The model must support the selected duration, resolution, ratio and audio option. Confirm these in your console. No prices are hard-coded or promised.

The first adapter supports text-to-video and one optional **first-frame image**, sent as base64 from the production folder. It does not attach every Character Bible image as identity references. For a two-person shot, prepare a starting composition containing both people and attach it to the shot. Keep identities and clothing in the prompt; review every result. The saved negative prompt is retained in the shot snapshot for reference; it is not sent as a separate unsupported API field.

Click Refresh status to query the asynchronous provider task. Successful clips are downloaded into `instance/clips/`; tasks and snapshots persist in `instance/vio_movie.db`. Download and approve from the clip library. Downloads that fail can be retried with Refresh without generating another task. If submission status is unknown, inspect BytePlus task history before resubmitting to avoid duplicate charges. Approval is stored in the clip library and does not overwrite the Shot List's manually managed production status.

Higgsfield is listed as integration pending and cannot be selected. No Higgsfield API support is claimed.

Official API contract: https://console.byteplus.com/ark/region%3Aap-southeast-1/docs/create-video-generation-task-api

## Data and security

Keep `.env`, `instance/`, source images and generated media out of git. Back up `instance/` locally: it contains your production database and clips. The app reads references from `VIO_PROJECT_PATH` (default `E:\Inkaka The Guru`) and does not move source assets. Keys stay on the backend and are not returned by the configuration endpoint. Live submissions send the prompt and selected reference to BytePlus. Demo mode does not send them.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests isolate the database in a temporary directory and mock the provider; they require no API key or paid generation.
