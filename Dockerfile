# Usa una imagen base de Python ligera pero robusta
FROM python:3.11-slim

# Evita que Python escriba archivos .pyc y fuerza salida de logs inmediata
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instala FFmpeg, soporte de fuentes y dependencias del sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Configura el directorio de trabajo
WORKDIR /app

# Copia e instala las dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código fuente
COPY main.py .

# Ejecuta el script
CMD ["python", "main.py"]
