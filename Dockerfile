FROM python:3.9-slim

# Instalar herramientas del sistema necesarias para video
RUN apt-get update && apt-get install -y ffmpeg libsm6 libxext6

WORKDIR /app

# Instalar las librerías de python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del programa
COPY main.py .

# Abrir el puerto 80
EXPOSE 80

# Iniciar el programa
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
