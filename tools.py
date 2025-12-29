import os
import json
import uuid 
import pytz
import traceback
import gspread
import random
import string
import requests
import re
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION")

if os.path.exists("service_account.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
else:
    print("⚠️ No se detectó 'service_account.json'. Usando identidad por defecto (Cloud Run).")

# --- CONFIGURACIÓN GOOGLE ---
TOKEN_FILE = 'token.json'
OAUTH_CREDENTIALS_FILE = 'credentials.json'
SPREADSHEET_ID_ASESOR = "1effw7xHg2YAUbfaxl9_o94-KTXnSSCLI3HOAHOmqmMs" 
SHEET_NAME_ASESOR = "Data"
SPREADSHEET_ID_WAREHOUSE = "1ltTQcqNAinOQ3N2HHEgb1pbRJkc9Da3miBdlBsgfidE" 
SHEET_NAME_INTERESADOS = "Interesados"
SHEET_NAME_NO_INTERESADOS = "No Interesados"

SCOPES = [
    'https://www.googleapis.com/auth/calendar', 
    'https://www.googleapis.com/auth/spreadsheets'
]

# --- CONFIGURACIÓN NEGOCIO ---
HORA_INICIO = 8  
HORA_FIN = 17    
DURACION_SLOT = 30 

CORREO_ASESOR_DEFAULT = "nicolas.cano@segurosbolivar.com"

def limpiar_respuesta_json(texto_respuesta):
    """
    Intenta extraer JSON válido usando Regex, ignorando texto extra o errores de formato markdown.
    """
    try:
        # 1. Si viene vacío o nulo
        if not texto_respuesta: return {}

        # 2. Búsqueda quirúrgica: Encuentra lo que esté entre llaves { ... }
        # re.DOTALL permite que el punto (.) coincida con saltos de línea
        match = re.search(r'\{.*\}', texto_respuesta, re.DOTALL)
        
        if match:
            json_str = match.group(0)
        else:
            # Si no encuentra llaves, intentamos limpiar a la fuerza
            json_str = texto_respuesta

        # 3. Limpieza de artefactos Markdown comunes
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        
        # 4. Intento de carga
        return json.loads(json_str)

    except Exception as e:
        print(f"⚠️ ERROR CRÍTICO PARSEANDO JSON: {e}")
        print(f"Texto recibido corrupto: {texto_respuesta}")
        return {}
    
def generar_codigo_solicitud():
    letras = list(string.ascii_uppercase)
    aleatorio1 = random.randint(0, 9)
    primera_letra = random.choice(letras) 
    aleatorio4 = random.randint(0, 9)
    aleatorio5 = random.randint(0, 9)
    aleatorio6 = random.randint(0, 9)
    aleatorio7 = random.randint(0, 9)
    segunda_letra = random.choice(letras)
    aleatorio8 = random.randint(0, 9)
    return f"LIA-{aleatorio1}{primera_letra}{aleatorio4}{aleatorio5}{aleatorio6}{aleatorio7}{segunda_letra}{aleatorio8}"

def construir_fila_por_columnas(mapa_datos):
    def col_a_indice(col_str):
        num = 0
        for c in col_str:
            if c in string.ascii_letters:
                num = num * 26 + (ord(c.upper()) - ord('A')) + 1
        return num - 1
    indices = {col_a_indice(k): v for k, v in mapa_datos.items()}
    max_index = max(indices.keys())
    fila = [''] * (max_index + 1)
    for idx, valor in indices.items():
        fila[idx] = valor
    return fila

def guardar_lead_sheet(datos_lead, info_cliente, asesor_asignado, fecha_cita):
    print("\n💾 Iniciando proceso de guardado (Interesados)...")
    if not os.path.exists(TOKEN_FILE): return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID_WAREHOUSE).worksheet(SHEET_NAME_INTERESADOS)
        
        tz_bogota = pytz.timezone('America/Bogota')
        fecha_radicacion = datetime.now(tz_bogota).strftime("%d/%m/%Y %H:%M:%S")
        id_unico = generar_codigo_solicitud()
        
        fecha_cita_formateada = ""
        if fecha_cita:
            try:
                dt_obj = datetime.fromisoformat(fecha_cita)
                fecha_cita_formateada = dt_obj.strftime("%d/%m/%Y %H:%M:%S")
            except ValueError: fecha_cita_formateada = fecha_cita
        
        mapa_fila = {
            'A': fecha_radicacion,
            'B': id_unico,
            'C': "LIA",
            'E': "LIA",
            'I': "Cita programada",
            'AB': info_cliente['nombre'],
            'AE': info_cliente['email'],
            'AD': info_cliente['telefono'],
            'AG': info_cliente['conjunto'],
            'AL': datos_lead.get('inmuebles', 'N/A'), 
            'AM': datos_lead.get('nivel_fondo', 'N/A'),
            'D': asesor_asignado,
            'BA': fecha_cita_formateada 
        }
        nueva_fila_lista = construir_fila_por_columnas(mapa_fila)
        sheet.append_row(nueva_fila_lista)
        print(f"✅ ¡ÉXITO! Registro guardado con ID: {id_unico}")
        return True
    except Exception as e:
        print(f"❌ Error escribiendo en Sheets: {e}")
        return False

def guardar_no_interesado_sheet(info_cliente, motivo_rechazo):
    print(f"\n💾 Registrando usuario NO INTERESADO. Motivo: {motivo_rechazo}")
    if not os.path.exists(TOKEN_FILE): return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID_WAREHOUSE).worksheet(SHEET_NAME_NO_INTERESADOS)
        
        tz_bogota = pytz.timezone('America/Bogota')
        fecha_radicacion = datetime.now(tz_bogota).strftime("%d/%m/%Y %H:%M:%S")
        
        fila_rechazo = [
            fecha_radicacion,           # A
            info_cliente['nombre'],     # B
            info_cliente['telefono'],   # C
            info_cliente['email'],      # D
            info_cliente['conjunto'],   # E
            motivo_rechazo              # F
        ]
        
        sheet.append_row(fila_rechazo)
        print(f"✅ Rechazo registrado correctamente.")
        return True
    except Exception as e:
        print(f"❌ Error guardando rechazo: {e}")
        traceback.print_exc()
        return False

def obtener_mejor_agente():
    """Replica la lógica de AssignLead de Apps Script en Python"""
    print("📊 Calculando el mejor agente desde Google Sheets...")
    
    if not os.path.exists(TOKEN_FILE):
        print("❌ Error: No hay token.")
        return None

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID_ASESOR).worksheet(SHEET_NAME_ASESOR)
        user_data = sheet.get_all_values()
        
        data_rows = user_data[1:]

        best_agent = None
        highest_effectiveness = -1
        best_sorting_key = float('inf')
        equity = 0.5

        for row in data_rows:
            if len(row) < 11: continue

            agent_name = row[1]
            email = row[2]
            novelty = row[4]

            try:
                total_capacity = float(row[5]) if row[5] else 0
                total_in_process = float(row[7]) if row[7] else 0
                eff_str = row[10].replace("%", "").strip()
                effectiveness = float(eff_str) if eff_str else 0
            except ValueError:
                continue

            if not novelty or novelty.strip() == "Activo":
                sorting_key = (-(1 - equity) * total_capacity) + (equity * total_in_process)

                if (sorting_key < best_sorting_key) or \
                   (sorting_key == best_sorting_key and effectiveness > highest_effectiveness):
                    
                    best_sorting_key = sorting_key
                    highest_effectiveness = effectiveness
                    best_agent = {"name": agent_name, "email": email}

        if best_agent:
            print(f"✅ Agente Ganador: {best_agent['email']} ({best_agent['name']})")
            return best_agent['email']
        else:
            print("⚠️ No hay agentes disponibles. Usando fallback.")
            return None

    except Exception as e:
        print(f"❌ Error en Sheets: {e}")
        traceback.print_exc()
        return None
    
def seleccionar_mejor_asesor(cliente_data):
    """
    Selecciona al asesor. 
    Actualmente usa el Default para pruebas.
    Descomentar el bloque para activar la inteligencia de Sheets.
    """
    print(f"🔄 Seleccionando asesor para cliente con {cliente_data.get('inmuebles')} inmuebles...")

    # --- 🔽 BLOQUE LÓGICA REAL (COMENTADO PARA PRUEBAS) 🔽 ---
    # agente_inteligente = obtener_mejor_agente()
    # if agente_inteligente:
    #     return agente_inteligente
    # ---------------------------------------------------------
    
    print(f"⚠️ Usando Asesor Default (Pruebas): {CORREO_ASESOR_DEFAULT}")
    return CORREO_ASESOR_DEFAULT

def validar_es_festivo(fecha_str):
    """
    Consulta api-colombia.com para ver si la fecha es festiva.
    Retorna: (True, "Nombre del Festivo") o (False, None)
    """
    print(f"🎉 Verificando si {fecha_str} es festivo en Colombia...")
    try:
        year = fecha_str.split("-")[0]
        
        url = f"https://api-colombia.com/api/v1/Holiday/year/{year}"
        
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return False, None
            
        festivos = response.json()
        
        for festivo in festivos:
            fecha_api = festivo.get("date", "")
            if fecha_api.startswith(fecha_str):
                nombre_festivo = festivo.get("name", "Festivo Nacional")
                print(f"🚫 Es festivo: {nombre_festivo}")
                return True, nombre_festivo
                
        return False, None

    except Exception as e:
        print(f"⚠️ Error consultando API Festivos: {e}")
        return False, None

def crear_evento_calendar(asesor_email, cliente_email, cliente_nombre, fecha_inicio_iso):
    print(f"🚀 Creando evento: {fecha_inicio_iso}")
    if not os.path.exists(TOKEN_FILE): return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        dt_inicio = datetime.fromisoformat(fecha_inicio_iso)
        dt_fin = dt_inicio + timedelta(minutes=30)
        request_id = str(uuid.uuid4())
        event_body = {
            'summary': f'Propuesta Jelpit - {cliente_nombre}',
            'description': f'Agenda Virtual.\nCliente: {cliente_email}\nAsesor: {asesor_email}',
            'start': {'dateTime': dt_inicio.isoformat(), 'timeZone': 'America/Bogota'},
            'end': {'dateTime': dt_fin.isoformat(), 'timeZone': 'America/Bogota'},
            'attendees': [{'email': cliente_email}, {'email': asesor_email}],
            'conferenceData': {'createRequest': {'requestId': request_id, 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}}
        }
        event_result = service.events().insert(calendarId=asesor_email, body=event_body, conferenceDataVersion=1, sendUpdates='all').execute()
        print(f"✅ Evento creado con ID: {event_result.get('id')}")
        return {
            "id": event_result.get('id'),
            "meet_link": event_result.get('hangoutLink'),
            "html_link": event_result.get('htmlLink')
        }
    except Exception as e:
        print(f"❌ Error evento: {e}")
        return False

def obtener_cupos_por_fecha(fecha_str, asesor_email):
    # Retorna una tupla: (Mensaje_Texto, Lista_Slots_Cruda)
    es_festivo, nombre_festivo = validar_es_festivo(fecha_str)
    if es_festivo:
        return f"ES FESTIVO: {nombre_festivo}", []
    
    print(f"\n🗓️ Analizando agenda BLINDADA para {fecha_str}")
    if not os.path.exists(TOKEN_FILE): return "Error Token", []
    
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        bogota_tz = pytz.timezone('America/Bogota')

        fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        dia_semana = fecha_dt.weekday()

        if dia_semana == 6:
            return "NO DISPONIBLE (DOMINGO)", []
        
        hora_cierre_hoy = 12 if dia_semana == 5 else HORA_FIN

        inicio_dia = bogota_tz.localize(datetime.combine(fecha_dt, datetime.min.time()))
        fin_dia = bogota_tz.localize(datetime.combine(fecha_dt, datetime.max.time()))

        events_result = service.events().list(
            calendarId=asesor_email, timeMin=inicio_dia.isoformat(), timeMax=fin_dia.isoformat(),
            singleEvents=True, orderBy='startTime', timeZone='America/Bogota'
        ).execute()
        events = events_result.get('items', [])
        
        start_work = inicio_dia.replace(hour=HORA_INICIO, minute=0, second=0)
        end_work = inicio_dia.replace(hour=hora_cierre_hoy, minute=0, second=0)
        
        slots_disponibles = []
        curr = start_work
        
        while curr < end_work:
            slot_end = curr + timedelta(minutes=DURACION_SLOT)
            if curr > datetime.now(bogota_tz): 
                ocupado = False
                for event in events:
                    start_raw = event['start'].get('dateTime', event['start'].get('date'))
                    end_raw = event['end'].get('dateTime', event['end'].get('date'))
                    try:
                        if 'T' in start_raw: 
                            ev_start = datetime.fromisoformat(start_raw)
                            ev_end = datetime.fromisoformat(end_raw)
                        else: 
                            ev_start = bogota_tz.localize(datetime.strptime(start_raw, "%Y-%m-%d"))
                            ev_end = bogota_tz.localize(datetime.strptime(end_raw, "%Y-%m-%d")) + timedelta(days=1)
                    except: continue

                    if ev_start.tzinfo is None: ev_start = ev_start.astimezone(bogota_tz)
                    if ev_end.tzinfo is None: ev_end = ev_end.astimezone(bogota_tz)

                    if (ev_start < slot_end) and (ev_end > curr):
                        if event.get('transparency') == 'transparent': continue
                        ocupado = True
                        break
                
                if not ocupado:
                    # Guardamos formato limpio para comparación exacta
                    slots_disponibles.append(curr.strftime('%I:%M %p').lower())

            curr = slot_end
        
        if slots_disponibles:
            nombres_dias = {0:'Lunes', 1:'Martes', 2:'Miércoles', 3:'Jueves', 4:'Viernes', 5:'Sábado', 6:'Domingo'}
            nombre_dia = nombres_dias[dia_semana]
            mensaje = f"CUPOS DISPONIBLES ({nombre_dia} {fecha_dt.day}):\n" + "\n".join([f"✅ {s}" for s in slots_disponibles])
            return mensaje, slots_disponibles # <--- AQUÍ RETORNAMOS LA LISTA TAMBIÉN
        else: 
            return "AGENDA LLENA", []

    except Exception as e:
        print(f"❌ Error obteniendo cupos: {e}")
        return "Error técnico verificando agenda.", []