FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN python -c "import pathlib, shutil; path = pathlib.Path('/app/execution'); shutil.rmtree(path) if path.exists() else None"
COPY . /app
RUN python -c "import pathlib, shutil; [shutil.rmtree(pathlib.Path('/app') / name) for name in ('config','execution','main','models','monitors','reporting','storage','wallet_scorer') if (pathlib.Path('/app') / f'{name}.py').exists() and (pathlib.Path('/app') / name).is_dir()]"

RUN chown -R appuser:appuser /app
USER appuser

VOLUME /app/data

CMD ["python", "main.py"]
