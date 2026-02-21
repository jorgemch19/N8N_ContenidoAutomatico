import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import ImageClip, concatenate_videoclips

app = FastAPI()

# Esta es la carpeta compartida con n8n
MEDIA_FOLDER = "/media"

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
        # Esto nos dirá qué archivos hay realmente en la carpeta
        todos_los_archivos = os.listdir(MEDIA_FOLDER)
        print(f"Contenido de la carpeta: {todos_los_archivos}")

        # 1. Buscar archivos que empiecen con el prefijo (ej: p1_)
        search_pattern = f"{req.prefix}_"
        files = [f for f in todos_los_archivos 
                 if f.startswith(search_pattern) and f.endswith(('.png', '.jpg', '.jpeg'))]
        
        # 2. Ordenarlos correctamente
        files.sort(key=natural_sort_key)

        if not files:
            # Ahora el error nos dirá qué archivos encontró en lugar de nada
            raise HTTPException(status_code=404, detail={
                "mensaje": f"No encontré imágenes con prefijo {req.prefix}",
                "archivos_vistos": todos_los_archivos,
                "ruta_buscada": MEDIA_FOLDER
            })

        # ... (el resto del código sigue igual)
        clips = []
        for filename in files:
            path = os.path.join(MEDIA_FOLDER, filename)
            clip = ImageClip(path).set_duration(2)
            clips.append(clip)

        final_video = concatenate_videoclips(clips, method="compose")
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)
        final_video.write_videofile(output_path, fps=24, codec="libx264")

        return {"estado": "ok", "archivo": output_path, "imagenes_usadas": len(files)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
