# Documentación del Pipeline de IA para Buzzy

Esta guía contiene los pasos exactos para llevar a producción el motor de Inteligencia Artificial que revisa audio (Faster-Whisper), visión (YOLOv11) y procesa todo en paralelo usando Celery y Redis.

## 1. Instalación de Dependencias del Sistema
Para que Whisper y la extracción de frames funcionen de forma ultra rápida, el servidor necesita las librerías de FFmpeg.

**En Ubuntu / Debian:**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install ffmpeg libavcodec-extra -y
```

**En Mac (Homebrew):**
```bash
brew install ffmpeg
```

## 2. Instalación de Librerías Python
Ejecuta el siguiente comando para instalar las herramientas de Deep Learning, Celery y Redis:
```bash
pip install -r requirements-ai.txt
```
*(Nota: La primera vez que corras una tarea, Faster-Whisper descargará el modelo "tiny" y YOLO descargará "yolov8n.pt", pesando menos de 100MB juntos).*

## 3. Ejecución en Paralelo (Producción / Local)
Para que el flujo funcione, debes tener **tres procesos** corriendo al mismo tiempo.

**Terminal 1: Redis Server**
```bash
redis-server
```

**Terminal 2: Django Backend**
```bash
cd Buzzy
python manage.py runserver
```

**Terminal 3: Celery Worker (El "Cerebro")**
Abre una terminal nueva en la carpeta donde está `manage.py` y corre el worker de Celery:
```bash
celery -A Buzzy worker --loglevel=info -P solo
```
*(Usa `-P solo` en Windows, en Linux/Mac puedes omitirlo o usar `-c 4` para usar 4 núcleos).*

---

## 4. Lógica de Polling Frontend (React)
Ya tienes el endpoint `/api/videos/create/`. Ahora, en tu componente de subida de React, debes inicializar un polling que verifique si el estado del video cambió de `processing` a `ready` o `blocked`.

Aquí tienes un esqueleto del componente y el Request:

```tsx
import React, { useState, useEffect } from 'react';
import { apiClient } from '../../client/api-client';

export default function VideoUploadForm() {
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [videoId, setVideoId] = useState<number | null>(null);
    const [status, setStatus] = useState<string>('idle'); // idle, pending, processing, ready, blocked

    const handleUpload = async () => {
        if (!file) return;
        setIsUploading(true);
        setStatus('pending');

        const formData = new FormData();
        formData.append('video', file);
        formData.append('description', 'Mi nuevo video!');

        try {
            // Llama al nuevo ViewSet que creamos
            const response = await apiClient.post('/api/videos/create/', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            
            // La DB devuelve el ID y el state 'pending'/'processing'
            setVideoId(response.data.video_id);
            setStatus(response.data.status);
        } catch (error) {
            console.error(error);
            setStatus('error');
        } finally {
            setIsUploading(false);
        }
    };

    // POLLING LÓGICA
    useEffect(() => {
        let interval: NodeJS.Timeout;

        if (videoId && (status === 'pending' || status === 'processing')) {
            // Verificar cada 5 segundos
            interval = setInterval(async () => {
                try {
                    // Reutiliza tu endpoint para obtener el video por ID
                    // (Asegurate de que traiga el campo 'status' serializado o crea uno simple)
                    const response = await apiClient.get(`/api/list-home/?id=${videoId}`); 
                    const videoData = response.data.results.find((v: any) => v.id === videoId);
                    
                    if (videoData) {
                        setStatus(videoData.status);
                        
                        if (videoData.status === 'ready') {
                            alert("¡Tu video fue revisado por IA y ya está publicado!");
                            clearInterval(interval);
                        } else if (videoData.status === 'blocked') {
                            alert(`El video ha sido bloqueado por el filtro familiar. Razón: ${videoData.safety_label}`);
                            clearInterval(interval);
                        }
                    }
                } catch (err) {
                    console.error("Error al poll el estado del video", err);
                }
            }, 5000);
        }

        return () => {
            if (interval) clearInterval(interval);
        };
    }, [videoId, status]);


    return (
        <div className="p-4 bg-gray-900 text-white rounded-lg max-w-sm mx-auto">
            <input type="file" accept="video/mp4" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            
            <button 
                onClick={handleUpload} 
                disabled={isUploading || !file}
                className="mt-4 bg-blue-600 px-4 py-2 rounded-lg"
            >
                {isUploading ? 'Subiendo...' : 'Publicar Video'}
            </button>

            {/* SKELETON UI */}
            {status === 'processing' && (
                <div className="mt-6 flex flex-col items-center animate-pulse">
                    <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                    <p className="mt-4 text-sm text-gray-400">Nuestra IA está analizando tu video (Audio y Visión)...</p>
                </div>
            )}
            
            {status === 'ready' && <p className="mt-6 text-green-500 font-bold">✅ Video Aprobado y en Línea</p>}
            {status === 'blocked' && <p className="mt-6 text-red-500 font-bold">❌ Video Bloqueado por IA</p>}
        </div>
    );
}
```
