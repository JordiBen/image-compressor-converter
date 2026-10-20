FROM apify/actor-python:3.13
COPY --chown=myuser:myuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && python -c "from PIL import features; assert features.check('avif') and features.check('webp'), 'AVIF/WebP missing'; import pillow_heif"
COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/ && python -c "import src.main"
CMD ["python3", "-m", "src"]
