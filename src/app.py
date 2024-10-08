import logging
import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from src.settings import UPLOAD_DIR
from src.transcribe import transcribe_file, transcribe_file_segment
from src.youtube_util import download_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# db
DB_ENABLED = False
try:
    import src.db as db

    DB_ENABLED = True
    logger.info("MongoDB enabled")
except Exception as e:
    db = None
    logger.error("MongoDB disabled")
    logger.error(e)

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = UPLOAD_DIR


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/transcriptions/input-files', methods=['POST'])
def transcribe():
    source_type = request.form['source_type']
    show_timestamps = request.form.get('show_timestamps') == 'on'
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    logger.info(f"{source_type}, show_timestamps: {show_timestamps}, start_time: {start_time}, end_time: {end_time}")

    meta = None
    upload_filepath = None
    try:
        if source_type == 'file':
            if 'audio_file' not in request.files:
                return jsonify({'error': 'No audio_file'}), 400

            file = request.files['audio_file']

            if file.filename == '':
                return jsonify({'error': 'No selected file'}), 400

            if file:
                filename = secure_filename(file.filename)
                upload_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(upload_filepath)
                meta = {'title': filename, 'src_type': 'file'}

        elif source_type == 'youtube':
            youtube_url = request.form.get('youtube_url')
            if not youtube_url:
                return jsonify({'error': 'No YouTube URL provided'}), 400
            if not youtube_url.startswith('https://www.youtube.com/'):
                return jsonify({'error': 'Not YouTube URL'}), 400

            upload_filepath, meta = download_audio(youtube_url)
            meta['src_type'] = 'youtube'
            logger.info(f"downloaded audio: '{upload_filepath}'")
        else:
            logger.error(f"Invalid source_type: {source_type}")
            return jsonify({'error': 'Invalid input'}), 400

    except Exception as e:
        logger.error(e, exc_info=True)
        return jsonify({'error': str(e)}), 500

    if start_time or end_time:
        result_file = transcribe_file_segment(upload_filepath, start_time, end_time, show_timestamps=show_timestamps)
    else:
        result_file = transcribe_file(upload_filepath, show_timestamps=show_timestamps)

    # rm uploaded file
    os.remove(upload_filepath)

    return jsonify(
        {'message': 'Transcription completed', 'output_file': result_file, 'transcript': Path(result_file).read_text(),
         'meta': meta})


@app.route('/transcriptions', methods=['POST'])
def save_transcript():
    if not DB_ENABLED:
        return jsonify({'error': 'DB not enabled'}), 400

    data = request.json
    doc = {
        'title': data.get('title'),
        'content': data.get('content'),
        'src_type': data.get('src_type'),
    }

    if data.get('channel'):
        doc['channel'] = data['channel']

    if not doc['content']:
        return jsonify({'error': 'No transcript'}), 400

    try:
        transcript_id = db.save_transcript(doc)
        logger.info(f"Saved transcript: {transcript_id}")
        return jsonify({'message': 'Transcript saved', 'id': transcript_id})
    except Exception as e:
        logger.error(e, exc_info=True)
        return jsonify({'error': 'Failed to save transcript'}), 500


@app.route('/transcriptions', methods=['GET'])
def get_transcript():
    transcript_id = request.args.get('id')
    if not transcript_id:
        return jsonify({'error': 'No transcript_id provided'}), 400

    try:
        res = db.get_transcript(transcript_id)
        return jsonify(res)
    except Exception as e:
        logger.error(e, exc_info=True)
        return jsonify({'error': 'Failed to get transcript'}), 500


@app.route('/search/transcripts', methods=['GET'])
def search_transcripts():
    if not DB_ENABLED:
        return jsonify({'error': 'DB not enabled'}), 400

    query = request.args.get('query', '')
    if not query:
        return jsonify({'error': 'No search query provided'}), 400

    try:
        results = db.search_transcripts(query)
        return jsonify({'results': results})
    except Exception as e:
        logger.error(e, exc_info=True)
        return jsonify({'error': 'Failed to search transcripts'}), 500


@app.route('/transcriptions', methods=['PUT'])
def update_transcript():
    if not DB_ENABLED:
        return jsonify({'error': 'DB not enabled'}), 400

    data = request.json
    id = request.args.get('id')
    if not id:
        return jsonify({'error': 'No transcript_id provided'}), 400

    if not data.get('content'):
        return jsonify({'error': 'No transcript'}), 400

    doc = {
        'content': data.get('content'),
    }

    try:
        res = db.update_transcript(id, doc)
        return jsonify({'message': f'Updated {res} transcript'})
    except Exception as e:
        logger.error(e, exc_info=True)
        return jsonify({'error': 'Failed to update transcript'}), 500


if __name__ == '__main__':
    app.run(debug=True)
