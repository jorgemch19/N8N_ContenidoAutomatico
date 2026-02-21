import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import ImageClip, concatenate_videoclips

app = FastAPI()

# Esta es la carpeta compartida con n8n
MEDIA_FOLDER = "/media_files"

class VideoRequest(BaseModel):
    prefix: str     # El prefijo del nombre (ej: "p1")
    output_name: str # El nombre del video final

def natural_sort_key(s):
    # Función para que ordene: 1, 2, ... 9, 10 (y no 1, 10, 2)
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

@app.post("/crear-video")
def crear_video(req: VideoRequest):
    try:
        # 1. Buscar archivos que empiecen con el prefijo (ej: p1_)
        search_pattern = f"{req.prefix}_"
        files = [f for f in os.listdir(MEDIA_FOLDER) 
                 if f.startswith(search_pattern) and f.endswith(('.png', '.jpg', '.jpeg'))]
        
        # 2. Ordenarlos correctamente
        files.sort(key=natural_sort_key)

        if not files:
            raise HTTPException(status_code=404, detail=f"No encontré imágenes que empiecen con {req.prefix} en {MEDIA_FOLDER}")

        # 3. Crear el video
        clips = []
        for filename in files:
            path = os.path.join(MEDIA_FOLDER, filename)
            # Cada imagen dura 2 segundos
            clip = ImageClip(path).set_duration(2)
            clips.append(clip)

        # Unir clips
        final_video = concatenate_videoclips(clips, method="compose")
        
        # Ruta de salida
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)
        
        # Guardar (24 fps es suficiente para imágenes estáticas)
        final_video.write_videofile(output_path, fps=24, codec="libx264")

        return {"estado": "ok", "archivo": output_path, "imagenes_usadas": len(files)}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
