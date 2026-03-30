"""
keywords.py — Buzzy category keyword registry
==============================================
Fuente de verdad única para categorización de videos.

Exporta 4 estructuras que usa tasks.py:
  KEYWORDS_PRO_MAP  → keywords por categoría (texto: transcript, tags, description)
  CLIP_PROMPTS      → descripciones visuales por categoría (análisis de frames con CLIP)
  YOLO_TO_CATEGORY  → objetos COCO detectados → categoría (análisis visual YOLO)
  CATEGORIAS_NOMBRES→ lista de nombres para seedear la DB

Reglas de mantenimiento:
  1. Cada keyword pertenece a UNA sola categoría — sin duplicados entre listas.
  2. NUNCA usar .extend() — devuelve None. Usar list() o [*lista1, *lista2].
  3. Para nueva categoría: añadir en los 4 bloques.
  4. CLIP_PROMPTS: más descriptivo = mejor precisión. Mínimo 4 frases por categoría.
"""

# ===========================================================================
# KEYWORDS POR CATEGORÍA
# ===========================================================================

KEYWORDS_NATURE = [
    # Felinos
    "tigre", "leon", "leona", "leopardo", "jaguar", "guepardo", "puma",
    "lince", "cheetah", "pantera",
    # Grandes mamíferos
    "oso", "lobo", "zorro", "coyote", "hiena", "jirafa", "elefante",
    "rinoceronte", "hipopotamo", "cebra", "bufalo", "antilope", "gacela",
    "gorila", "chimpance", "orangutan", "mono", "mandril", "koala",
    "canguro", "panda", "oso polar", "alce", "ciervo", "bisonte",
    # Domésticos y granja
    "perro", "gato", "conejo", "hamster", "cobaya", "loro", "canario",
    "tortuga", "pez", "mascota", "cachorro", "gatito", "puppy", "kitten",
    "pet", "vaca", "caballo", "cerdo", "oveja", "cabra", "gallina",
    "pato", "ganso", "burro", "mula",
    # Reptiles
    "serpiente", "cocodrilo", "caiman", "iguana", "camaleon", "gecko",
    "boa", "piton", "cobra", "vibora", "lagarto", "salamandra",
    # Aves
    "aguila", "halcon", "buho", "tucan", "flamenco ave", "pinguino",
    "pelicano", "guacamayo", "colibri", "cuervo", "pajaro", "ave",
    "condor", "albatros", "garza",
    # Marinos
    "tiburon", "delfin", "ballena", "orca", "pulpo", "calamar", "medusa",
    "cangrejo", "langosta", "coral", "arrecife", "foca", "morsa",
    "mantarraya", "caballito de mar",
    # Insectos
    "mariposa", "abeja", "hormiga", "escarabajo", "arana", "escorpion",
    "libelula", "grillo", "mariquita",
    # Hábitats
    "selva", "safari", "sabana", "jungla", "bosque", "pradera", "tundra",
    "pantano", "manglar", "ecosistema", "biodiversidad",
    "reserva natural", "parque natural", "zoo", "zoologico", "acuario",
    # Conceptos
    "depredador", "presa", "cazador", "manada", "bandada", "cardumen",
    "migracion", "hibernacion", "camuflaje", "veneno", "picadura",
    "fauna", "flora", "especie", "mamifero", "reptil", "anfibio",
    "silvestre", "salvaje", "extincion", "conservacion", "naturaleza",
    # Inglés
    "animal", "animals", "nature", "wildlife", "predator", "prey",
    "bird", "dog", "cat", "tiger", "lion", "bear", "wolf", "snake",
    "shark", "dolphin", "whale", "elephant", "giraffe", "monkey",
    "wild", "exotic", "habitat",
]

KEYWORDS_FITNESS = [
    # Entrenamiento general
    "entrenamiento", "gym", "ejercicio", "rutina", "fitness", "dieta",
    "calorias", "musculo", "entrenar", "gimnasio", "crossfit", "fuerza",
    "resistencia", "flexibilidad", "bienestar", "proteina", "suplemento",
    "pesa", "mancuerna", "cardio", "abs", "gluteo", "pierna", "espalda",
    "brazo", "coach", "entrenador",
    # Deportes de equipo
    "futbol", "baloncesto", "basket", "tenis", "voleibol", "rugby",
    "balonmano", "beisbol", "hockey", "cricket",
    # Deportes individuales
    "atletismo", "natacion", "ciclismo", "boxeo", "mma", "karate",
    "judo", "lucha", "taekwondo", "esgrima", "golf", "padel", "badminton",
    # Running y outdoor
    "correr", "running", "maraton", "triatlon", "senderismo", "escalada",
    "montanismo", "trail", "ultramaraton", "mountainbike",
    # Deportes de deslizamiento
    "esqui", "snowboard", "surf", "skate", "patinaje", "wakeboard",
    # Competición
    "campeon", "torneo", "partido", "competencia", "jugador", "equipo",
    "victoria", "derrota", "marcador", "estadio", "cancha", "pista",
    "arbitro", "regla", "falta", "penal", "gol", "canasta",
    "record deportivo", "podio", "medalla", "trofeo", "copa", "liga",
    "olimpico", "mundial deportivo", "clasificacion", "rival",
    # Equipo deportivo
    "balon", "pelota", "raqueta", "bate", "guante", "casco deportivo",
    "bicicleta", "ring", "octogono", "tatami", "cesped", "campo deportivo",
    # Gym específico
    "calentamiento", "estiramiento", "hidratacion", "electrolitos", "sudor",
    "quemar grasa", "definicion", "volumen", "masa muscular",
    "cronometro", "repeticion", "serie", "descanso", "recuperacion",
    "lesion", "fisioterapia", "masaje deportivo", "agujetas",
    "potencia", "velocidad", "agilidad", "coordinacion", "equilibrio",
    "postura", "pulso", "ritmo cardiaco", "hiit", "tabata", "calistenia",
    "barras", "dominadas", "flexiones", "sentadillas", "zancadas",
    "plancha", "abdominales", "core", "lumbar", "triceps", "biceps",
    "pecho", "cuadriceps", "isquios", "gemelos", "tobillo", "rodilla",
    "cadera", "barra gym", "disco gym", "banco gym", "polea", "cinta",
    "eliptica", "remo gym", "spinning", "burpee", "deadlift",
    "squat", "press", "bench press", "bodybuilding", "powerlifting",
    "strongman", "workout", "yoga", "pilates", "zumba", "mindfulness",
    # Inglés
    "sport", "sports", "athlete", "training", "exercise", "muscle",
    "weight lifting", "run", "swim", "fight", "championship", "fitness",
]

KEYWORDS_DEPORTES = KEYWORDS_FITNESS

KEYWORDS_GAMING = [
    # Plataformas
    "playstation", "xbox", "nintendo", "switch", "steam", "pc gaming",
    "consola", "mando", "joystick", "teclado gamer", "raton gamer",
    "auriculares gamer", "silla gamer", "monitor gamer", "rgb", "setup gamer",
    # Cultura gaming
    "gamer", "gaming", "videojuego", "gameplay", "partida", "stream gaming",
    "twitch", "e-sports", "clan", "equipo gamer", "torneo gaming",
    "competitivo gaming", "pro player", "streamer",
    # Juegos populares
    "fortnite", "minecraft", "roblox", "valorant", "league of legends",
    "dota", "cs go", "counter strike", "overwatch", "apex legends",
    "warzone", "gta", "fifa gamer", "call of duty", "halo", "zelda",
    "mario", "pokemon", "sonic", "mortal kombat", "street fighter",
    # Mecánicas
    "nivel", "boss", "mision", "multijugador", "online gaming", "rango",
    "skin", "lag", "ping", "fps gaming", "graficos", "mod", "estrategia juego",
    "aventura juego", "rpg", "shooter", "battle royale", "jugabilidad",
    "mecanica juego", "truco juego", "secreto juego", "easter egg",
    "bug juego", "glitch", "parche", "dlc", "expansion juego",
    "personaje juego", "avatar", "habilidad juego", "arma juego",
    "municion", "inventario", "item", "loot", "cofre", "recompensa juego",
    "logro", "platino", "ranked", "noob", "bot", "npc",
    "mapa juego", "sandbox", "simulacion juego", "puzzle", "indie",
    "unreal engine", "unity engine", "demo", "beta juego", "trailer juego",
    # Streaming
    "donacion", "chat gaming", "cooperativo", "crossplay", "cloud gaming",
    "vr gaming", "retro gaming", "arcade", "emulador", "rom",
    "hp vida", "mana", "xp", "levear", "farmear", "grindear",
    "campear", "rushear", "combo", "ultimate", "speedrun",
    "epic games", "game pass",
    # Inglés
    "game", "games", "play", "player", "gamer", "gaming", "esports",
    "controller", "console", "video game", "streamer",
]

KEYWORDS_MUSIC = [
    # Elementos musicales
    "cancion", "musica", "ritmo", "cover", "instrumento", "guitarra",
    "piano", "voz cantante", "cantar", "beat", "melodia", "armonia",
    "acorde", "nota musical", "escala musical", "solfeo", "partitura",
    # Producción
    "productor musical", "estudio grabacion", "grabacion", "mezcla",
    "masterizacion", "ecualizacion", "autotune", "reverb", "delay",
    "distorsion", "pedal", "amplificador", "sintetizador", "sampler",
    "daw", "ableton", "fl studio", "pro tools",
    # Presentación
    "concierto", "show musical", "escenario", "festival musical", "gira",
    "tour musical", "recital", "opera", "backstage", "soundcheck",
    # Industria
    "artista musical", "banda musical", "grupo musical", "album",
    "disco musical", "sencillo", "single", "ep musica", "letras",
    "componer", "compositor", "cantante", "interprete", "musico",
    "vocalista", "rapero", "mc", "dj", "sello discografico",
    "discografica", "independiente musical", "grammy", "billboard",
    "hit musical", "playlist", "spotify", "apple music", "soundcloud",
    "tidal", "youtube music", "radio", "vinilo", "cd musica",
    # Géneros
    "rock", "pop", "trap", "reggaeton", "jazz", "clasica", "electronica",
    "techno", "house music", "dance", "folk", "country", "blues",
    "soul", "funk", "metal", "punk", "ska", "reggae", "salsa",
    "merengue", "bachata", "cumbia", "vallenato", "flamenco", "tango",
    "bolero", "mariachi", "norteño", "drill", "lofi", "chill",
    "ambient", "hip hop", "rap", "rnb", "kpop", "indie music",
    # Instrumentos
    "bajo", "bateria", "percusion", "teclado musical", "violin",
    "flauta", "trompeta", "saxofon", "orquesta", "coro",
    "guitarra electrica", "guitarra acustica", "ukulele", "arpa",
    # Rap/urbano
    "freestyle", "batalla de rap", "rima", "verso", "estribillo",
    "puente musical", "intro", "outro", "remix", "mashup",
    # Lugares y eventos
    "fiesta", "discoteca", "club nocturno", "rave", "after party",
    "dancefloor", "banda sonora", "ost",
    # Técnica
    "acustico", "sonido", "frecuencia", "decibelios", "altavoz",
    "microfono", "afinacion", "tono",
    # Inglés
    "music", "song", "singer", "band", "concert", "album", "lyrics",
    "melody", "chorus", "verse", "instrumental", "acoustic", "track",
]

KEYWORDS_TRAVEL = [
    # Planificación
    "viaje", "destino", "vacaciones", "itinerario", "escapada",
    "fin de semana viaje", "aventura viaje", "explorar", "turismo",
    "turista", "mochilero", "backpacker", "nomada digital",
    # Transporte
    "avion", "vuelo", "aeropuerto", "aerolinea", "escala vuelo",
    "embarque", "tren viaje", "autobus viaje", "metro viaje",
    "taxi", "coche alquiler", "crucero", "ferry",
    # Alojamiento
    "hotel", "hostal", "airbnb", "resort", "camping", "glamping",
    "apartamento viaje", "posada", "alojamiento",
    # Documentos y logística
    "pasaporte", "visa", "maleta", "equipaje", "mochila viaje",
    "seguro viaje", "moneda extranjera", "cambio divisas",
    "propina", "presupuesto viaje", "reserva viaje",
    # Geografía
    "playa", "montana viaje", "ciudad", "pueblo", "isla", "costa",
    "acantilado", "faro", "puerto", "lago", "rio", "cascada",
    "volcan", "glaciar",
    # Cultura y turismo
    "monumento", "museo", "ruinas", "castillo", "iglesia", "catedral",
    "palacio", "plaza", "barrio historico", "mercado local",
    "gastronomia local", "comida tipica", "tradicion cultural",
    "festival local", "carnaval viaje", "souvenir",
    # Experiencias
    "mirador", "vistas", "atardecer viaje", "amanecer viaje",
    "foto viaje", "vlog viaje", "experiencia", "recuerdo",
    "excursion", "tour guiado", "ecoturismo",
    # Conceptos
    "libertad", "aventurero", "globetrotter", "viajero", "mundo",
    "planeta", "continente", "pais", "cultura extranjera",
    # Inglés
    "travel", "trip", "vacation", "holiday", "backpacking", "tourism",
    "tourist", "flight", "destination", "explore", "journey",
    "abroad", "passport", "luggage", "sightseeing",
]

KEYWORDS_HUMOR = [
    "risa", "gracioso", "broma", "chiste", "divertido", "humor",
    "comedia", "lol", "xd", "fail", "reir", "parodia", "sketch",
    "bromista", "gracia", "carcajada", "meme", "troll", "burla",
    "ironia", "sarcasmo", "comediante", "jajaja", "funny", "joke",
    "prank", "laugh", "hilarious", "rofl", "lmao",
    "reaccion", "reaccionando", "standup", "bloopers", "fail video",
    "compilation", "momentos graciosos", "clip gracioso", "video viral",
    "wtf", "random", "absurdo", "locura", "ingenioso", "epico",
    "ridiculo", "payaso", "mueca", "payasada", "bobada", "tonteria",
    "bizarro", "bromear", "burlarse", "jocoso", "ludico", "festivo",
    "viral", "tendencia", "memes", "dank meme", "cringe", "awkward",
    "comedy", "reaction", "blooper", "roast",
]

KEYWORDS_TECH = [
    # Dispositivos
    "celular", "iphone", "android", "computadora", "laptop", "tablet",
    "ipad", "smartwatch", "reloj inteligente", "audifonos tech",
    "camara tech", "dron", "robot", "impresora 3d",
    # Marcas
    "apple", "samsung", "google", "microsoft", "sony", "huawei",
    "xiaomi", "tesla", "nvidia", "amd", "intel",
    # Software y desarrollo
    "software", "hardware", "app", "aplicacion", "programacion", "codigo",
    "desarrollo", "web", "internet", "nube", "cloud", "api",
    "base datos", "sql", "python", "java", "javascript", "html",
    "css", "react", "frontend", "backend", "fullstack", "dev",
    "devops", "git", "github", "ingenieria software", "ux", "ui",
    "prototipo", "sistema operativo", "macos", "windows", "linux",
    # Inteligencia artificial
    "ia", "inteligencia artificial", "machine learning", "deep learning",
    "neural", "algoritmo", "chatgpt", "openai", "llm", "gpt",
    "computer vision", "nlp", "data science", "big data",
    # Conectividad
    "wifi", "5g", "bluetooth", "fibra optica", "satelite", "iot",
    "smart home", "domotica",
    # Hardware específico
    "procesador", "ram", "bateria tech", "carga rapida", "ssd", "hdd",
    "memoria tech", "usb", "hdmi", "pantalla", "oled", "amoled",
    "4k", "8k", "led tech", "monitor tech", "mouse", "teclado tech",
    "periferico", "giga", "tera", "mega", "bit", "byte",
    # Crypto
    "blockchain", "cripto", "bitcoin", "ethereum", "nft", "web3",
    "fintech", "defi",
    # Contenido tech
    "review tech", "unboxing", "gadget", "tecnologia", "tech",
    "innovacion", "startup", "silicon valley", "ciberseguridad", "vpn",
    "hacker etico", "bug bounty",
    # Ciencia
    "telescopio", "microscopio", "laboratorio", "cientifico",
    "invento", "patente", "nanotecnologia", "laser", "dna", "genetica",
    # Inglés
    "technology", "tech", "software", "hardware", "coding",
    "programming", "developer", "computer", "phone", "device",
    "digital", "cyber", "innovation", "gadget", "review", "unboxing",
]

KEYWORDS_FOOD = [
    # Cocina y preparación
    "receta", "cocinar", "ingredientes", "cocina", "asado", "frito",
    "horno", "sarten", "wok", "vapor", "hervido", "estofado", "guiso",
    "salteado", "parrillada", "barbacoa", "grill", "ahumado",
    "fermentacion", "masa", "amasado", "horneado",
    # Comidas del día
    "desayuno", "almuerzo", "cena", "merienda", "brunch", "aperitivo",
    # Restaurantes
    "restaurante", "chef", "gastronomia", "menu", "degustacion",
    "buffet", "banquete", "catering", "cafeteria", "food truck",
    "panaderia", "pasteleria", "heladeria", "cevicheria",
    # Sabores
    "delicioso", "sabor", "sabroso", "postre", "dulce", "salado",
    "picante", "agridulce", "amargo", "umami", "gourmet", "artesanal",
    "casero", "tipico", "regional", "internacional", "organico",
    "fresco", "crujiente", "suave", "jugoso", "tostado", "dorado",
    "glaseado", "emplatado",
    # Bebidas
    "bebida", "vino", "cerveza", "cafe", "te", "infusion", "jugo",
    "refresco", "soda", "agua mineral", "champagne", "coctel", "trago",
    "whisky", "ron", "tequila", "mezcal", "gin", "vodka", "licor",
    "bartender", "sommelier", "cata", "maridaje", "copa", "vaso",
    # Ingredientes
    "azucar", "sal", "pimienta", "aceite", "vinagre", "ajo", "cebolla",
    "tomate", "papa", "arroz", "frijoles", "lentejas", "garbanzos",
    "huevo", "queso", "mantequilla", "crema", "yogur", "leche",
    "harina", "levadura", "especias", "condimento", "hierbas",
    # Alimentos específicos
    "helado", "pastel", "tarta", "galleta", "caramelo", "miel",
    "mermelada", "chocolate", "fruta", "verdura", "carne",
    "pollo", "mariscos", "salmon", "atun", "langostino",
    "vegetariano", "vegano", "sin gluten", "keto",
    # Cocinas del mundo
    "sushi", "ramen", "udon", "tempura", "sashimi",
    "pizza", "pasta", "lasana", "espagueti", "risotto",
    "taco", "burrito", "quesadilla", "guacamole", "ceviche",
    "curry", "pad thai", "pho", "kimchi", "hummus", "falafel",
    "shawarma", "paella", "empanada", "arepas",
    # Técnicas
    "juliana", "brunoise", "mise en place", "sazon", "aroma comida",
    "textura", "paladar",
    # Utensilios
    "tenedor", "cuchillo cocina", "cuchara", "vajilla", "cristaleria",
    "estufa", "microondas", "licuadora", "batidora", "cafetera",
    "nevera", "congelador",
    # Contenido
    "michelin", "sibarita", "food tour", "hambre",
    # Inglés
    "food", "cooking", "recipe", "tasty", "delicious", "yummy",
    "chef", "restaurant", "cuisine", "meal", "dish", "eat", "drink",
    "bake", "grill", "fry", "cook", "kitchen", "ingredients",
]

KEYWORDS_FASHION = [
    # Core moda
    "maquillaje", "outfit", "ropa", "estilo", "skincare", "look",
    "vestido", "maquillar", "moda", "fashion", "belleza",
    "tendencia moda", "glamour", "elegante", "casual", "diseno moda",
    "pasarela", "modelo moda",
    # Cuidado personal
    "piel", "rostro", "cabello", "pelo", "peinado", "corte cabello",
    "tinte", "unas", "manicura", "pedicura", "depilacion", "afeitado",
    "barba", "bigote",
    # Skincare
    "crema", "serum", "labial", "sombras", "base maquillaje",
    "corrector", "pestanas", "cejas", "hidratacion piel",
    "limpieza piel", "rutina skincare", "mascarilla facial", "tonico",
    "exfoliacion", "protector solar", "bronceado",
    # Perfumería
    "perfume", "fragancia", "colonia",
    # Ropa y accesorios
    "accesorios", "joyas", "bolso", "zapatos", "tenis moda", "sneakers",
    "tacones", "botas", "sandalias", "seda", "algodon", "lana moda",
    "cuero", "denim", "jeans", "pantalones", "camisa", "camiseta",
    "blusa", "falda", "chaqueta", "abrigo", "sueter", "sudadera",
    "hoodie", "short", "bermuda", "traje", "esmoquin", "corbata",
    "pajarita", "cinturon", "sombrero", "gorra", "lentes", "gafas",
    "reloj moda", "anillo", "pulsera", "collar moda", "aretes",
    "pendientes", "piercing", "tatuaje moda", "ropa interior",
    "lenceria", "pijama", "bata",
    # Marcas y lujo
    "marca moda", "luxury", "lujo", "boutique", "disenador", "costura",
    "alta costura",
    # Compras
    "shopping", "compras", "tienda moda", "descuento", "rebajas",
    "oferta moda", "haul", "try on", "lookbook",
    # Cabello
    "champu", "acondicionador", "fijador", "gel cabello", "espuma",
    "laca", "cepillo", "peine", "secador", "plancha cabello", "rizador",
    # Estilos
    "vintage moda", "retro moda", "minimalista moda", "maximalista",
    "gotico", "hippie", "bohemio", "chic", "urbano moda", "streetwear",
    "legging", "top deportivo",
    # Colores y texturas
    "paleta colores moda", "neon", "glitter", "purpurina", "lentejuelas",
    "bordado", "estampado", "flores moda", "rayas", "cuadros",
    "animal print", "camuflaje moda",
    # Contenido beauty
    "tutorial maquillaje", "selfi moda", "ootd", "pose", "actitud",
    "confianza", "empoderamiento", "cuerpo positivo", "alfombra roja",
    "influencer beauty",
    # Inglés
    "beauty", "makeup", "style", "fashion", "clothing", "outfit",
    "skincare", "haircare", "nails", "accessories", "model", "runway",
    "luxury brand", "shopping haul", "ootd", "lookbook",
]

# ===========================================================================
# FUENTE DE VERDAD — importar este dict en tasks.py
# ===========================================================================

KEYWORDS_PRO_MAP: dict[str, list[str]] = {
    "Humor":                 list(KEYWORDS_HUMOR),
    "Tecnología":            list(KEYWORDS_TECH),
    "Gastronomía":           list(KEYWORDS_FOOD),
    "Moda y Belleza":        list(KEYWORDS_FASHION),
    "Deportes y Fitness":    list(dict.fromkeys(KEYWORDS_FITNESS + KEYWORDS_DEPORTES)),
    "Viajes":                list(KEYWORDS_TRAVEL),
    "Música":                list(KEYWORDS_MUSIC),
    "Gaming":                list(KEYWORDS_GAMING),
    "Naturaleza y Animales": list(KEYWORDS_NATURE),
}

# ===========================================================================
# PROMPTS CLIP — descripciones visuales por categoría
# Usar en _category_scores_from_clip() para comparar frames con CLIP.
# Más frases específicas = mayor precisión. Mínimo 4 por categoría.
# ===========================================================================

CLIP_PROMPTS: dict[str, list[str]] = {
    "Música": [
        "a person singing on stage with a microphone",
        "musicians playing instruments in a concert",
        "a DJ mixing music at a nightclub",
        "a band performing live on stage with lights",
        "person playing guitar or piano instrument",
        "recording studio with microphone and headphones",
        "music festival crowd with stage lights",
    ],
    "Gaming": [
        "person playing video games with a controller",
        "gaming setup with RGB lights and multiple monitors",
        "esports tournament with players at computers",
        "streamer playing video games on camera with facecam",
        "video game screen showing gameplay characters",
        "gaming chair keyboard mouse rgb desk setup",
        "person wearing headset playing online game",
    ],
    "Gastronomía": [
        "delicious food dish beautifully plated on table",
        "chef cooking in a professional restaurant kitchen",
        "restaurant table with gourmet meal and wine",
        "person eating tasty street food",
        "fresh ingredients and cooking preparation",
        "baking pastry or bread in kitchen",
        "food market with colorful fruits and vegetables",
    ],
    "Deportes y Fitness": [
        "athlete training hard lifting weights in a gym",
        "people playing football soccer or basketball match",
        "runner competing in a marathon race on road",
        "person doing bodybuilding workout exercises",
        "sports competition in stadium with crowd",
        "martial arts boxing or mma fighting",
        "yoga or pilates fitness class outdoors",
    ],
    "Viajes": [
        "tourist visiting famous landmark or monument",
        "beautiful landscape travel destination panoramic view",
        "person at airport with luggage boarding plane",
        "exotic tropical beach paradise vacation",
        "mountain hiking adventure travel nature",
        "exploring city streets local culture tourism",
        "travel vlog exploring new country and food",
    ],
    "Moda y Belleza": [
        "fashion model wearing stylish trendy outfit",
        "makeup tutorial beauty transformation close up face",
        "skincare routine applying products to face",
        "clothing haul try on fashion videos",
        "luxury brand accessories shoes handbag",
        "hair styling salon haircut coloring",
        "beauty influencer cosmetics products review",
    ],
    "Tecnología": [
        "unboxing new smartphone gadget tech review",
        "computer programming writing code on screen",
        "tech review latest device smartphone or laptop",
        "robot or artificial intelligence futuristic technology",
        "person using computer developing software app",
        "drone flying aerial technology camera",
        "high tech gaming pc setup with rgb hardware",
    ],
    "Humor": [
        "person laughing doing something funny or silly",
        "prank or fail compilation funny viral video",
        "comedian performing standup comedy on stage",
        "meme reaction funny internet video moment",
        "group of friends laughing together having fun",
        "unexpected funny accident blooper moment",
        "funny animals or people doing silly things",
    ],
    "Naturaleza y Animales": [
        "wild tiger lion or leopard in natural jungle habitat",
        "cute dog or cat pet animal portrait close up",
        "wildlife safari animals in african savanna",
        "exotic colorful tropical birds in nature",
        "underwater ocean marine animals fish sharks dolphins",
        "nature landscape forest mountains with wild animals",
        "zoo exotic animals or wildlife photography",
    ],
}

# ===========================================================================
# YOLO COCO OBJECTS → CATEGORÍA
# Solo clases del dataset COCO estándar (80 clases).
# Peso de la señal YOLO es menor que CLIP — usar como refuerzo.
# ===========================================================================

YOLO_TO_CATEGORY: dict[str, str] = {
    # Naturaleza y Animales
    "cat":            "Naturaleza y Animales",
    "dog":            "Naturaleza y Animales",
    "bird":           "Naturaleza y Animales",
    "horse":          "Naturaleza y Animales",
    "cow":            "Naturaleza y Animales",
    "sheep":          "Naturaleza y Animales",
    "elephant":       "Naturaleza y Animales",
    "bear":           "Naturaleza y Animales",
    "zebra":          "Naturaleza y Animales",
    "giraffe":        "Naturaleza y Animales",
    # Deportes y Fitness
    "sports ball":    "Deportes y Fitness",
    "tennis racket":  "Deportes y Fitness",
    "skateboard":     "Deportes y Fitness",
    "bicycle":        "Deportes y Fitness",
    "surfboard":      "Deportes y Fitness",
    "baseball bat":   "Deportes y Fitness",
    "baseball glove": "Deportes y Fitness",
    "frisbee":        "Deportes y Fitness",
    "skis":           "Deportes y Fitness",
    "snowboard":      "Deportes y Fitness",
    "kite":           "Deportes y Fitness",
    # Gastronomía
    "pizza":          "Gastronomía",
    "hot dog":        "Gastronomía",
    "cake":           "Gastronomía",
    "sandwich":       "Gastronomía",
    "donut":          "Gastronomía",
    "apple":          "Gastronomía",
    "banana":         "Gastronomía",
    "orange":         "Gastronomía",
    "broccoli":       "Gastronomía",
    "carrot":         "Gastronomía",
    "bowl":           "Gastronomía",
    "wine glass":     "Gastronomía",
    "cup":            "Gastronomía",
    "fork":           "Gastronomía",
    "spoon":          "Gastronomía",
    "bottle":         "Gastronomía",
    "dining table":   "Gastronomía",
    "microwave":      "Gastronomía",
    "oven":           "Gastronomía",
    "refrigerator":   "Gastronomía",
    "toaster":        "Gastronomía",
    # Tecnología
    "laptop":         "Tecnología",
    "cell phone":     "Tecnología",
    "keyboard":       "Tecnología",
    "tv":             "Tecnología",
    "remote":         "Tecnología",
    "mouse":          "Tecnología",
    "monitor":        "Tecnología",
    # Viajes
    "airplane":       "Viajes",
    "train":          "Viajes",
    "bus":            "Viajes",
    "suitcase":       "Viajes",
    "backpack":       "Viajes",
    "boat":           "Viajes",
    "motorcycle":     "Viajes",
    # Moda y Belleza
    "tie":            "Moda y Belleza",
    "handbag":        "Moda y Belleza",
    "umbrella":       "Moda y Belleza",
    # Gaming (ambiguo — solo refuerza si hay otras señales)
    "chair":          "Gaming",
}

# ===========================================================================
# CATEGORÍAS EN LA DB — sincronizado con KEYWORDS_PRO_MAP
# ===========================================================================

CATEGORIAS_NOMBRES: list[str] = list(KEYWORDS_PRO_MAP.keys())