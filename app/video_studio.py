"""Local-first video jobs. Demo mode never contacts a paid provider."""
import base64
import json
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify, render_template, request, send_file
from app.character_store import DATABASE_PATH
from app.episode_store import get_episode
from app.shot_store import list_shots

studio = Blueprint('studio', __name__)
BASE_URL = 'https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks'
MEDIA = DATABASE_PATH.parent / 'clips'


def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS video_jobs (
        id TEXT PRIMARY KEY, episode_id INTEGER NOT NULL, shot_number INTEGER NOT NULL,
        provider TEXT NOT NULL, status TEXT NOT NULL, snapshot TEXT NOT NULL,
        remote_id TEXT, video_url TEXT, local_file TEXT, error TEXT NOT NULL DEFAULT '',
        approved INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    db.commit()
    return db


def public(row):
    value = dict(row)
    value['snapshot'] = json.loads(value['snapshot'])
    value.pop('local_file', None)
    # Signed provider links stay on the backend; downloads are copied locally.
    value.pop('video_url', None)
    value['clip_url'] = '/api/video/jobs/' + value['id'] + '/clip' if row['local_file'] else None
    return value


def get_job(job_id):
    with connect() as db:
        row = db.execute('SELECT * FROM video_jobs WHERE id=?', (job_id,)).fetchone()
    if row is None:
        raise LookupError('Take not found.')
    return row


def update(job_id, **fields):
    with connect() as db:
        db.execute('UPDATE video_jobs SET ' + ','.join(key + '=?' for key in fields) + ' WHERE id=?', (*fields.values(), job_id))


def ark(method, suffix='', payload=None):
    key = os.getenv('BYTEPLUS_API_KEY', '').strip()
    if not key:
        raise ValueError('Add BYTEPLUS_API_KEY to your local .env and restart Vio-Movie.')
    req = Request(BASE_URL + suffix, data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method=method)
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        # Do not echo provider bodies, tokens or request headers into the browser.
        messages = {401: 'API key rejected.', 403: 'Model access denied. Check model activation and account access.',
                    429: 'Provider rate limit or quota reached. Check credits and retry later.'}
        raise ValueError(messages.get(error.code, 'Provider rejected the request (HTTP %s). Check model, inputs and account credit.' % error.code)) from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError('Could not reach BytePlus or read its response. Try refreshing later.') from None


def copy_video(job_id, url):
    if urlparse(url).scheme != 'https':
        raise ValueError('Provider returned an invalid video download URL.')
    MEDIA.mkdir(parents=True, exist_ok=True)
    target = MEDIA / (job_id + '.mp4')
    temporary = target.with_suffix('.part')
    try:
        # No API credentials are sent to the media host.
        with urlopen(url, timeout=60) as response, temporary.open('wb') as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 250 * 1024 * 1024:
                    raise ValueError('Clip exceeds the 250 MB local download limit.')
                output.write(chunk)
        temporary.replace(target)
    except (OSError, URLError, TimeoutError):
        raise ValueError('Video is ready but download failed. Refresh this take to retry.') from None
    finally:
        temporary.unlink(missing_ok=True)
    return target.name


@studio.before_request
def local_mutations():
    if request.method in ('POST', 'PUT', 'DELETE'):
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            return jsonify(error='Cross-origin changes are not allowed.'), 403


@studio.errorhandler(ValueError)
def bad_input(error):
    return jsonify(error=str(error)), 400


@studio.errorhandler(LookupError)
def missing(error):
    return jsonify(error=str(error)), 404


@studio.get('/studio')
def page():
    return render_template('studio.html')


@studio.get('/api/video/settings')
def settings():
    return jsonify(demo=True, live_enabled=os.getenv('VIDEO_LIVE_ENABLED', '').lower() == 'true',
                   key_configured=bool(os.getenv('BYTEPLUS_API_KEY', '').strip()),
                   model=os.getenv('BYTEPLUS_VIDEO_MODEL', ''),
                   providers=[{'id': 'demo', 'name': 'Demo — free workflow test'},
                              {'id': 'seedance', 'name': 'Seedance — BytePlus ModelArk'},
                              {'id': 'higgsfield', 'name': 'Higgsfield — integration pending', 'disabled': True}])


@studio.get('/api/video/jobs')
def jobs():
    with connect() as db:
        rows = db.execute('SELECT * FROM video_jobs ORDER BY created_at DESC, rowid DESC').fetchall()
    return jsonify(jobs=[public(row) for row in rows])


@studio.post('/api/video/jobs')
def create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('Send shot settings as JSON.')
    try:
        episode_id, number = int(data.get('episode_id', 0)), int(data.get('shot_number', 0))
    except (ValueError, TypeError):
        raise ValueError('Select an episode and shot.') from None
    if not get_episode(episode_id):
        raise LookupError('Episode not found.')
    shots = list_shots(episode_id)
    if number < 1 or number > len(shots):
        raise ValueError('Save a shot list first, then select a shot.')
    shot = dict(shots[number - 1])
    provider = data.get('provider', 'demo')
    if provider not in ('demo', 'seedance'):
        raise ValueError('This provider is not integrated yet.')
    prompt = data.get('prompt', shot.get('prompt', ''))
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ValueError('Enter a prompt of 1–20,000 characters.')
    try:
        duration = int(data.get('duration', 5))
    except (ValueError, TypeError):
        raise ValueError('Choose a supported duration.') from None
    if duration not in (5, 6, 8, 10):
        raise ValueError('Choose 5, 6, 8 or 10 seconds.')
    ratio, resolution = data.get('ratio', '16:9'), data.get('resolution', '720p')
    if ratio not in ('16:9', '9:16', '1:1') or resolution not in ('480p', '720p', '1080p'):
        raise ValueError('Choose a supported aspect ratio and resolution.')
    model = data.get('model', os.getenv('BYTEPLUS_VIDEO_MODEL', ''))
    if not isinstance(model, str) or len(model) > 200:
        raise ValueError('Invalid model ID.')
    reference = data.get('reference', '')
    if not isinstance(reference, str) or reference and reference not in shot.get('reference_images', []):
        raise ValueError('Choose a reference attached to this saved shot.')
    shot.update(prompt=prompt.strip(), duration_seconds=duration, model=model.strip(), ratio=ratio,
                resolution=resolution, selected_reference=reference, generate_audio=data.get('generate_audio') is True)
    payload = {'model': model.strip(), 'content': [{'type': 'text', 'text': shot['prompt']}],
               'duration': duration, 'ratio': ratio, 'resolution': resolution, 'generate_audio': shot['generate_audio']}
    if provider == 'seedance':
        if os.getenv('VIDEO_LIVE_ENABLED', '').lower() != 'true':
            raise ValueError('Live generation is disabled. Use Demo until you are ready to spend credits.')
        if data.get('confirm_paid') is not True:
            raise ValueError('Confirm that this generation may spend provider credits.')
        if not model.strip():
            raise ValueError('Enter your activated BytePlus model or endpoint ID.')
        if reference:
            root = Path(os.getenv('VIO_PROJECT_PATH', r'E:\Inkaka The Guru')).expanduser().resolve()
            candidate = (root / reference).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                raise ValueError('Reference image must exist inside the production folder.')
            if candidate.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp') or candidate.stat().st_size > 10 * 1024 * 1024:
                raise ValueError('Use a JPG, PNG or WebP reference smaller than 10 MB.')
            mime = mimetypes.guess_type(candidate.name)[0]
            uri = 'data:' + mime + ';base64,' + base64.b64encode(candidate.read_bytes()).decode()
            payload['content'].append({'type': 'image_url', 'image_url': {'url': uri}, 'role': 'first_frame'})
    job_id = uuid.uuid4().hex
    # Persist before submitting: a network timeout must not silently auto-submit another paid task.
    with connect() as db:
        db.execute('INSERT INTO video_jobs (id,episode_id,shot_number,provider,status,snapshot) VALUES (?,?,?,?,?,?)',
                   (job_id, episode_id, number, provider, 'queued' if provider == 'demo' else 'submitting', json.dumps(shot)))
    if provider == 'seedance':
        try:
            result = ark('POST', payload=payload)
            if not isinstance(result.get('id'), str) or not result['id']:
                raise ValueError('Provider did not return a task ID. Check your BytePlus task history before retrying.')
            update(job_id, remote_id=result['id'], status='queued')
        except ValueError as error:
            update(job_id, status='submission_unknown', error=str(error) + ' Check BytePlus task history before creating another take.')
    return jsonify(job=public(get_job(job_id))), 201


@studio.post('/api/video/jobs/<job_id>/refresh')
def refresh(job_id):
    job = get_job(job_id)
    if job['provider'] == 'demo':
        if job['status'] == 'queued':
            update(job_id, status='running')
        elif job['status'] == 'running':
            update(job_id, status='demo_ready')
    elif job['remote_id'] and job['status'] not in ('succeeded', 'failed', 'expired', 'cancelled'):
        result = ark('GET', '/' + quote(job['remote_id'], safe=''))
        status = result.get('status')
        if status not in ('queued', 'running', 'succeeded', 'failed', 'expired', 'cancelled'):
            raise ValueError('Unrecognized provider status. Refresh later.')
        if status == 'succeeded':
            url = (result.get('content') or {}).get('video_url')
            if not isinstance(url, str):
                raise ValueError('Provider has not returned a video URL yet.')
            # Keep remote ID and nonterminal state if download fails; refresh retries download only.
            filename = copy_video(job_id, url)
            update(job_id, status=status, local_file=filename, error='')
        else:
            update(job_id, status=status, error='Provider did not complete this take. Check BytePlus task history.' if status in ('failed', 'expired', 'cancelled') else '')
    return jsonify(job=public(get_job(job_id)))


@studio.post('/api/video/jobs/<job_id>/import')
def import_clip(job_id):
    job = get_job(job_id)
    if job['provider'] != 'demo' or job['local_file']:
        raise ValueError('Import a clip into an empty demo take only.')
    clip = request.files.get('clip')
    if not clip or Path(clip.filename or '').suffix.lower() != '.mp4':
        raise ValueError('Select an MP4 clip.')
    MEDIA.mkdir(parents=True, exist_ok=True)
    target = MEDIA / (job_id + '.mp4')
    temporary = target.with_suffix('.part')
    try:
        clip.save(temporary)
        with temporary.open('rb') as stream:
            header = stream.read(32)
        if b'ftyp' not in header:
            raise ValueError('File does not have a valid MP4 container header.')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    update(job_id, local_file=target.name, status='imported')
    return jsonify(job=public(get_job(job_id)))


@studio.post('/api/video/jobs/<job_id>/approve')
def approve(job_id):
    job = get_job(job_id)
    if not job['local_file']:
        raise ValueError('Only a saved video clip can be approved. Demo placeholders are not generated footage.')
    with connect() as db:
        db.execute('UPDATE video_jobs SET approved=0 WHERE episode_id=? AND shot_number=?', (job['episode_id'], job['shot_number']))
        db.execute('UPDATE video_jobs SET approved=1 WHERE id=?', (job_id,))
    return jsonify(job=public(get_job(job_id)))


@studio.get('/api/video/jobs/<job_id>/clip')
def clip(job_id):
    job = get_job(job_id)
    if not job['local_file']:
        raise LookupError('This take has no saved video.')
    return send_file(MEDIA / job['local_file'], mimetype='video/mp4', conditional=True,
                     as_attachment=request.args.get('download') == '1', download_name='episode-%s-shot-%s-%s.mp4' % (job['episode_id'], job['shot_number'], job_id[:8]))
