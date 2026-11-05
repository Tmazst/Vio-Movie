import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.character_store as characters
import app.episode_store as episodes
import app.shot_store as shots
import app.video_studio as video
from run import app


class VideoStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(module, 'DATABASE_PATH', root / 'test.db')
                        for module in (characters, episodes, shots, video)]
        self.patches += [patch.object(video, 'MEDIA', root / 'clips'),
                         patch.dict(os.environ, {'VIDEO_LIVE_ENABLED': 'false', 'BYTEPLUS_API_KEY': 'test-secret'})]
        for item in self.patches:
            item.start()
        self.client = app.test_client()
        self.episode = episodes.save_episode({'episode_number': 1, 'title': 'Kitchen'})
        shots.save_shots(self.episode['id'], [{'prompt': 'Gogo in the kitchen', 'duration_seconds': 5}])
        self.body = {'episode_id': self.episode['id'], 'shot_number': 1, 'provider': 'demo'}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def create(self, **changes):
        result = self.client.post('/api/video/jobs', json={**self.body, **changes})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json['job']

    def test_demo_never_calls_provider_and_preserves_snapshot(self):
        with patch.object(video, 'ark', side_effect=AssertionError('paid call')):
            job = self.create()
            shots.save_shots(self.episode['id'], [{'prompt': 'Changed prompt'}])
            for status in ('running', 'demo_ready'):
                response = self.client.post('/api/video/jobs/' + job['id'] + '/refresh')
                self.assertEqual(response.json['job']['status'], status)
            stored = self.client.get('/api/video/jobs').json['jobs'][0]
            self.assertEqual(stored['snapshot']['prompt'], 'Gogo in the kitchen')
            self.assertIsNone(stored['clip_url'])
            self.assertEqual(self.client.post('/api/video/jobs/' + job['id'] + '/approve').status_code, 400)

    def test_live_requires_enable_and_explicit_acknowledgement(self):
        with patch.object(video, 'ark') as provider:
            self.assertEqual(self.client.post('/api/video/jobs', json={**self.body, 'provider': 'seedance'}).status_code, 400)
            with patch.dict(os.environ, {'VIDEO_LIVE_ENABLED': 'true'}):
                self.assertEqual(self.client.post('/api/video/jobs', json={**self.body, 'provider': 'seedance', 'model': 'model'}).status_code, 400)
            provider.assert_not_called()
        self.assertNotIn('test-secret', self.client.get('/api/video/settings').get_data(as_text=True))

    def test_live_submission_poll_and_download_retry_without_resubmit(self):
        with patch.dict(os.environ, {'VIDEO_LIVE_ENABLED': 'true'}), patch.object(video, 'ark', side_effect=[{'id': 'remote-1'}, {'status': 'succeeded', 'content': {'video_url': 'https://example.com/clip.mp4'}}, {'status': 'succeeded', 'content': {'video_url': 'https://example.com/clip.mp4'}}]) as provider:
            job = self.create(provider='seedance', model='test-model', confirm_paid=True)
            with patch.object(video, 'copy_video', side_effect=[ValueError('download failed'), 'saved.mp4']):
                self.assertEqual(self.client.post('/api/video/jobs/' + job['id'] + '/refresh').status_code, 400)
                result = self.client.post('/api/video/jobs/' + job['id'] + '/refresh')
                self.assertEqual(result.json['job']['status'], 'succeeded')
            self.assertEqual([call.args[0] for call in provider.call_args_list], ['POST', 'GET', 'GET'])

    def test_ambiguous_submission_stays_visible(self):
        with patch.dict(os.environ, {'VIDEO_LIVE_ENABLED': 'true'}), patch.object(video, 'ark', side_effect=ValueError('timeout')):
            job = self.create(provider='seedance', model='test-model', confirm_paid=True)
        self.assertEqual(job['status'], 'submission_unknown')
        self.assertIn('task history', job['error'])

    def test_import_preview_and_single_approved_take(self):
        ids = [self.create()['id'], self.create()['id']]
        data = b'\x00\x00\x00\x18ftypisom' + bytes(30)
        for job_id in ids:
            response = self.client.post('/api/video/jobs/' + job_id + '/import', data={'clip': (io.BytesIO(data), 'clip.mp4')})
            self.assertEqual(response.status_code, 200)
            clip = self.client.get('/api/video/jobs/' + job_id + '/clip')
            self.assertEqual(clip.data, data)
            clip.close()
            self.assertEqual(self.client.post('/api/video/jobs/' + job_id + '/approve').status_code, 200)
        jobs = self.client.get('/api/video/jobs').json['jobs']
        self.assertEqual(sum(j['approved'] for j in jobs), 1)
        self.assertEqual(next(j['id'] for j in jobs if j['approved']), ids[1])

    def test_invalid_payload_provider_reference_origin(self):
        for values in ({'provider': 'higgsfield'}, {'duration': 3}, {'reference': '../secret.png'}, {'shot_number': 99}):
            self.assertEqual(self.client.post('/api/video/jobs', json={**self.body, **values}).status_code, 400)
        self.assertEqual(self.client.post('/api/video/jobs', json=[], headers={'Origin': 'https://other.test'}).status_code, 403)
        self.assertEqual(self.client.post('/api/video/jobs', json=[]).status_code, 400)
        self.assertEqual(self.client.get('/studio').status_code, 200)


if __name__ == '__main__':
    unittest.main()
