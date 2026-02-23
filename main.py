import os
import re
import numpy as np
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import concatenate_videoclips, AudioFileClip, CompositeAudioClip, VideoClip, CompositeVideoClip, ColorClip, ImageClip
from typing import List, Optional

app = FastAPI()
MEDIA_FOLDER = "/media"

class VideoRequest(BaseModel):
    prefix: str
    output_name: str
    audio_bg: str = "taudio-1.mp3"
    audio_impact: str = "impacto.mp3" # Archivo del Boom inicial
    cta_img: str = "cta.png"          # Archivo del logo transparente (¡Pásalo por remove.bg!)

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def create_vignette_clip(width=1080, height=1920, duration=10):
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    X, Y = np.meshgrid(x, y)
    R = np.sqrt(X**2 + Y**2)
    mask = np.clip((R - 0.5) / 0.7, 0, 0.6)
    black = np.zeros((height, width, 3), dtype=np.uint8)
    vignette = ImageClip(black).set_duration(duration)
    mask_clip = ImageClip(mask, ismask=True).set_duration(duration)
    return vignette.set_mask(mask_clip)

def create_smooth_zoom_clip(img_path, duration, zoom_in=True, target_w=1080, target_h=1920):
    img = Image.open(img_path).convert('RGB')
    
    # Color Pop
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    
    img_w, img_h = img.size
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h

    if img_ratio > target_ratio:
        new_w = img_h * target_ratio
        new_h = img_h
    else:
        new_w = img_w
        new_h = img_w / target_ratio

    left = (img_w - new_w) / 2
    top = (img_h - new_h) / 2
    zoom_factor = 0.15 
    
    def make_frame(t):
        progress = t / duration
        if zoom_in:
            current_zoom = 1.0 - (zoom_factor * progress)
        else:
            current_zoom = (1.0 - zoom_factor) + (zoom_factor * progress)
        
        current_w = new_w * current_zoom
        current_h = new_h * current_zoom
        center_x = left + new_w / 2
        center_y = top + new_h / 2
        
        c_left = center_x - current_w / 2
        c_top = center_y - current_h / 2
        c_right = center_x + current_w / 2
        c_bottom = center_y + current_h / 2
        
        cropped = img.crop((c_left, c_top, c_right, c_bottom))
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
        return np.array(resized)

    return VideoClip(make_frame, duration=duration)

def create_text_overlay_image(text, output_path, width=1080, height=200):
    # Crear imagen transparente
    img = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # Intentar cargar fuente instalada en Docker, si falla usa default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 80)
    except IOError:
        font = ImageFont.load_default()

    # Calcular tamaño del texto para centrarlo (método compatible con Pillow 9.5.0)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    x = (width - text_w) / 2
    y = (height - text_h) / 2

    # Dibujar sombra (borde negro) para que se lea bien
    shadow_offset = 3
    draw.text((x+shadow_offset, y+shadow_offset), text, font=font, fill=(0, 0, 0, 255))
    # Dibujar texto principal (Amarillo o Blanco, aquí puse un amarillo tipo TikTok)
    draw.text((x, y), text, font=font, fill=(255, 220, 0, 255))

    img.save(output_path, "PNG")
    return output_path

@app.post("/crear-video")
def crear_video(req: VideoRequest):
    try:
        # 1. Rutas
        audio_main_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_audio_guion.mp3")
        if not os.path.exists(audio_main_path):
            audio_main_path = audio_main_path.replace(".mp3", ".wav")
            
        bg_music_path = os.path.join(MEDIA_FOLDER, req.audio_bg)
        subs_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_subtitulos.ass")
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)
        
        impact_path = os.path.join(MEDIA_FOLDER, req.audio_impact)
        cta_path = os.path.join(MEDIA_FOLDER, req.cta_img)

        # 2. Audio Complejo
        main_audio = AudioFileClip(audio_main_path)
        duration = main_audio.duration
        audio_layers = [main_audio]
        
        if os.path.exists(bg_music_path):
            bg_audio = AudioFileClip(bg_music_path).volumex(0.1).set_duration(duration)
            audio_layers.append(bg_audio)
            
        # Impacto Grave al inicio
        if os.path.exists(impact_path):
            impact_audio = AudioFileClip(impact_path).volumex(0.8)
            if impact_audio.duration > duration:
                impact_audio = impact_audio.subclip(0, duration)
            audio_layers.append(impact_audio.set_start(0.0))
            
        final_audio = CompositeAudioClip(audio_layers)

        # 3. Procesar Imágenes (Base)
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        num_images = len(img_files)
        base_duration = duration / num_images
        transition_time = 0.5 

        clips = []
        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            clip_duration = base_duration + transition_time
            zoom_in = (i % 2 == 0)
            
            clip = create_smooth_zoom_clip(path, clip_duration, zoom_in=zoom_in)
            if i > 0:
                clip = clip.crossfadein(transition_time)
            clips.append(clip)

        base_video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        base_video = base_video.set_duration(duration)

        # 4. Capas Visuales Superiores
        video_layers = [base_video]
        
        # Capa Viñeteado
        vignette_layer = create_vignette_clip(width=1080, height=1920, duration=duration)
        video_layers.append(vignette_layer)

        # Capa Flash Blanco (Hook)
        flash_duration = 0.5
        white_flash = ColorClip(size=(1080, 1920), color=(255, 255, 255)).set_duration(flash_duration)
        white_flash = white_flash.crossfadeout(flash_duration)
        video_layers.append(white_flash)

        # Animación CTA Limpia (Deslizamiento Ease-Out)
        cta_duration = 3.0
        if os.path.exists(cta_path) and duration > cta_duration:
            start_cta = duration - cta_duration
            # Cargamos el logo obligando a MoviePy a reconocer la transparencia (has_mask=True)
            cta_clip = ImageClip(cta_path).resize(width=250)
            
            # Función de deslizamiento suave desde la derecha
            def cta_slide(t):
                # En los primeros 0.5 segundos, se mueve de X=1080 a X=800
                if t < 0.5:
                    x = 1080 - (280 * (t / 0.5))
                else:
                    x = 800 # Se queda quieto en X=800
                return (x, 1000) # Y=1000 (altura de los botones de TikTok)

            cta_clip = cta_clip.set_position(cta_slide).set_start(start_cta).set_duration(cta_duration)
            video_layers.append(cta_clip)

        # 5. Composición Final
        final_video = CompositeVideoClip(video_layers)
        final_video = final_video.set_audio(final_audio)

        # 6. Renderizado Optimizado
        final_video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            bitrate="5000k",
            threads=4,
            preset="ultrafast",
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )

        return {"estado": "ok", "video": req.output_name}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- NUEVO MODELO PARA EL VIDEO 2 ---
class MarcadorTiempo(BaseModel):
    texto: str     # Ej: "Día 1"
    tiempo: float  # Ej: 0.0 (segundos)

class VideoRequestV2(BaseModel):
    prefix: str
    output_name: str
    audio_bg: str = "taudio-1.mp3"
    audio_impact: str = "impacto.mp3"
    cta_img: str = "cta.png"
    num_imagenes: int 
    marcadores: Optional[List[MarcadorTiempo]] = [] # Nueva lista de tiempos

# --- NUEVO ENDPOINT PARA EL VIDEO 2 ---
@app.post("/crear-video-2")
def crear_video_2(req: VideoRequestV2):
    try:
        # 1. Rutas
        audio_main_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_audio_guion.mp3")
        if not os.path.exists(audio_main_path):
            audio_main_path = audio_main_path.replace(".mp3", ".wav")
            
        bg_music_path = os.path.join(MEDIA_FOLDER, req.audio_bg)
        subs_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_subtitulos.ass")
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)
        
        impact_path = os.path.join(MEDIA_FOLDER, req.audio_impact)
        cta_path = os.path.join(MEDIA_FOLDER, req.cta_img)

        # 2. Audio Complejo
        main_audio = AudioFileClip(audio_main_path)
        duration = main_audio.duration
        audio_layers = [main_audio]
        
        if os.path.exists(bg_music_path):
            bg_audio = AudioFileClip(bg_music_path).volumex(0.1).set_duration(duration)
            audio_layers.append(bg_audio)
            
        # SONIDO DE IMPACTO PARA CADA MARCADOR DE TIEMPO
        if os.path.exists(impact_path) and req.marcadores:
            for marcador in req.marcadores:
                if marcador.tiempo < duration:
                    # Añade el boom en el segundo exacto
                    impact_audio = AudioFileClip(impact_path).volumex(0.8).set_start(marcador.tiempo)
                    audio_layers.append(impact_audio)
        elif os.path.exists(impact_path) and not req.marcadores:
            # Si no hay marcadores, ponemos el boom solo al inicio por defecto
            impact_audio = AudioFileClip(impact_path).volumex(0.8).set_start(0.0)
            if impact_audio.duration > duration:
                impact_audio = impact_audio.subclip(0, duration)
            audio_layers.append(impact_audio)
            
        final_audio = CompositeAudioClip(audio_layers)

        # 3. Procesar Imágenes con NUEVA LÓGICA DE TIEMPOS
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)
        
        img_files = img_files[:req.num_imagenes]

        transition_time = 0.5 
        clips = []
        tiempo_acumulado = 0.0

        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            zoom_in = (i % 2 == 0)
            
            if i == len(img_files) - 1:
                tiempo_restante = duration - tiempo_acumulado
                tiempo_base_clip = max(1.0, tiempo_restante)
            else:
                if i % 2 == 0:
                    tiempo_base_clip = 2.5
                else:
                    tiempo_base_clip = 3.5
                tiempo_acumulado += tiempo_base_clip

            clip_duration = tiempo_base_clip + transition_time
            clip = create_smooth_zoom_clip(path, clip_duration, zoom_in=zoom_in)
            if i > 0:
                clip = clip.crossfadein(transition_time)
            clips.append(clip)

        base_video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        base_video = base_video.set_duration(duration)

        # 4. Capas Visuales Superiores
        video_layers = [base_video]
        
        vignette_layer = create_vignette_clip(width=1080, height=1920, duration=duration)
        video_layers.append(vignette_layer)

        # TEXTOS VISUALES EN PANTALLA (LOS MARCADORES)
        if req.marcadores:
            for i, marcador in enumerate(req.marcadores):
                # Calcular cuánto dura en pantalla este texto
                if i + 1 < len(req.marcadores):
                    # Dura hasta que empiece el siguiente marcador
                    texto_duration = req.marcadores[i+1].tiempo - marcador.tiempo
                else:
                    # Si es el último, dura hasta el final del video
                    texto_duration = duration - marcador.tiempo
                
                # Crear imagen PNG transparente con el texto
                temp_img_path = os.path.join(MEDIA_FOLDER, f"temp_marcador_{i}.png")
                create_text_overlay_image(marcador.texto, temp_img_path)
                
                # Convertirlo en clip, ponerlo arriba (y=150) y asignarle sus tiempos
                txt_clip = ImageClip(temp_img_path) \
                            .set_start(marcador.tiempo) \
                            .set_duration(texto_duration) \
                            .set_position(("center", 150)) # Posición Y = 150px (arriba)
                
                # Efecto FadeIn rápido para que entre suave
                txt_clip = txt_clip.crossfadein(0.3)
                video_layers.append(txt_clip)

        flash_duration = 0.5
        white_flash = ColorClip(size=(1080, 1920), color=(255, 255, 255)).set_duration(flash_duration)
        white_flash = white_flash.crossfadeout(flash_duration)
        video_layers.append(white_flash)

        cta_duration = 3.0
        if os.path.exists(cta_path) and duration > cta_duration:
            start_cta = duration - cta_duration
            cta_clip = ImageClip(cta_path).resize(width=250)
            
            def cta_slide(t):
                if t < 0.5:
                    x = 1080 - (280 * (t / 0.5))
                else:
                    x = 800
                return (x, 1000)

            cta_clip = cta_clip.set_position(cta_slide).set_start(start_cta).set_duration(cta_duration)
            video_layers.append(cta_clip)

        # 5. Composición Final
        final_video = CompositeVideoClip(video_layers)
        final_video = final_video.set_audio(final_audio)

        # 6. Renderizado Optimizado
        final_video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            bitrate="5000k",
            threads=4,
            preset="ultrafast",
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )
        
        # Limpieza de imágenes temporales de texto (opcional)
        for i in range(len(req.marcadores)):
            temp_path = os.path.join(MEDIA_FOLDER, f"temp_marcador_{i}.png")
            if os.path.exists(temp_path):
                os.remove(temp_path)

        return {"estado": "ok", "video": req.output_name}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
