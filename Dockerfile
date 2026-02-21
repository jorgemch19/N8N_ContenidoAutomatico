# Usa una imagen oficial de Python ligera
FROM python:3.11-slim

# Instala FFmpeg y fuentes estándar necesarias para subtítulos
RUN apt-get update && \
    apt-get install -y ffmpeg fonts-liberation && \
    rm -rf /var/lib/apt/lists/*

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos de requerimientos e instala dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código fuente
COPY main.py .

# Expone el puerto 8000 para n8n
EXPOSE 8000

# Levanta el servidor FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
