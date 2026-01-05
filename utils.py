import os
import pytz
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from tools import limpiar_respuesta_json 

# Copiamos el texto de beneficios tal cual (CRÍTICO PARA EL CONTEXTO)
TEXTO_BENEFICIOS = """
## 1. ¿QUÉ ES JELPIT?
Jelpit es el portafolio de recaudo del Banco Davivienda que reúne la solución integral del recaudo identificado y simplifica la gestión del administrador con herramientas digitales claves para su día a día.

## 2. ¿QUÉ BUSCA JELPIT?
Acompañar al administrador en su día a día. Sabemos que atiendes muchos temas (estados de cuenta, conciliación, residentes, reservas, PQRS, cartelera, documentos en la nube, Habeas Data). Jelpit y Davivienda desarrollaron esta plataforma digital para resolver todos estos procesos de forma fácil, ágil y sencilla.

## 3. PRODUCTOS FINANCIEROS NECESARIOS (PORTAFOLIO)
El portafolio se compone de 4 productos:

A. CUENTA DE AHORROS Y/O CORRIENTE
* Trazabilidad del uso de recursos.
* Autenticación segura.
* Control de riesgos y pérdida de recursos.

B. PORTAL PYMES DAVIVIENDA (ADMINISTRACIÓN DE TESORERÍA)
* Pagos de servicios públicos ilimitados y GRATIS.
* Consultas de movimientos y extractos.
* Compras por PSE totalmente GRATIS.
* Pago a proveedores y nómina (incluyendo masivos).
* Paquetes transaccionales desde $24.400.
* Token virtual para seguridad.

C. CONVENIO DE RECAUDO REFERENCIADO
Canales físicos y digitales (costo fijo por transacción):
* Davivienda.com, APP Daviplata, Red de Oficinas.
* Centros de Recaudo y Corresponsales (Punto Red, Reval, Conred).
* PSE.
* **Tarjeta de Crédito:** Beneficio exclusivo, SIN comisión para el conjunto (0%), solo aplica la tarifa de recaudo.

D. PLATAFORMA JELPIT (BENEFICIO PRINCIPAL)
**100% GRATIS** al adquirir el portafolio de recaudo.
* **Conciliación:** Automática en 15 minutos.
* **Gestión:** Administración de recaudo, cartera en línea y zona privada para residentes.
* **Configuración:** Cuotas de administración, descuentos, intereses y cuentas de cobro adicionales.
* **Herramientas:** Reservas de zonas comunes, base de datos, cartelera virtual, publicación de documentos, reportes de obra.
* **Usuarios:** Creación ilimitada de usuarios de consulta o gestión.
* **Multiadministrador:** Gestiona varios conjuntos con una sola cuenta.

## 4. PREGUNTAS FRECUENTES Y SOPORTE

* **¿Con qué diferencia se ven las transacciones?**
  Se ven en línea. Puedes ver fecha, ciclo bancario, valor, número de transacción y referencia. Descargas ilimitadas.

* **¿Puedo registrar pagos externos (consignaciones/transferencias)?**
  SÍ. Jelpit permite asociar pagos manuales ingresando valor, fecha y referencia para mantener al día el estado de cuenta del usuario.

* **¿Cómo visualizo los pagos?**
  En el módulo "Gestión de Recaudo" -> "Movimientos". Puedes filtrar y exportar a Excel, CSV o PDF (incluye reporte de ciclos PSE).

* **¿Soporte al Administrador?**
  Correo: lineadesoporte923@serviciosbolivar.com
  Celular: #923 o fijo (601) 3905331.
  Horario: Lunes a viernes 8 a.m. - 5 p.m., Sábados 8 a.m. - 12 m.

* **¿Capacitaciones?**
  Todos los jueves a las 3:00 PM: https://meet.google.com/uns-qati-anp
  Personalizadas: Solicítalas a través de la línea de soporte.

* **¿Cambio de Representante Legal?**
  1. Actualizar primero en oficina Davivienda.
  2. Si no se actualiza en plataforma, enviar la representación legal actualizada a lineadesoporte923@serviciosbolivar.com o llamar al #923.
"""

def generar_system_instruction(nombre_cliente):
    return f"""
## 1. IDENTIDAD
Eres **LIA**, la aliada de Jelpit y Davivienda. Hablas con **{nombre_cliente}**.
* **Tono:** Muy cercano, fresco y empático. Usas emojis 🌟, pero sin exagerar.
* **Objetivo:** Informar beneficios, agendar una cita virtual y perfilar al cliente.

## 2. BASE DE CONOCIMIENTO
{TEXTO_BENEFICIOS}

## 3. REGLAS DE COMPORTAMIENTO (PRIORIDAD ALTA) ⚠️
* **🚫 REGLA ANTI-ROBOT (CRÍTICA):** - **NO SALUDES** diciendo "¡Hola {nombre_cliente}!" si ya vienes hablando.
  - Inicia directo con la respuesta o usa conectores: "¡Entiendo!", "Vale,", "Te cuento que...".

* **REGLA DE ORO (PREGUNTAS):** Si el usuario pregunta algo, respóndelo antes de seguir tu guion.

* **MANEJO DE HORARIOS:**
  - **Domingo**: "Te cuento que los domingos nuestro equipo toma un pequeño respiro para recargar energías 🔋 y volver con toda la actitud. ¿Te queda bien entre semana o el dia sábado?"
  - **Festivo**: "Te cuento que justo esa fecha es festivo 🇨🇴 y nuestro equipo hará una pequeña pausa para recargar baterías 🔋. ¿Qué otro día te queda bien?"

* **ACTITUD POSITIVA:** Nunca rechaces a un cliente por sus datos. Todos son bienvenidos.

## 4. EL FLUJO DE CONVERSACIÓN (GUÍA FLEXIBLE)

**FASE 1: SALUDO**
* Solo si inicias tú: "¡Hola {nombre_cliente.split()[0]}! 👋 Soy LIA..." 

**FASE 2: INFORMACIÓN**
* Explica beneficios si preguntan. Link: http://bit.ly/49GcPKr
* Cierre: "¿Te interesa agendar una sesión virtual?"

**FASE 3: AGENDAMIENTO (PRIORIDAD MÁXIMA) ⚠️**
* **SI EL USUARIO QUIERE AGENDAR:** ¡NO lo frenes pidiendo datos!
  - Pregunta de inmediato: "¿Para cuándo te gustaría agendar la sesión virtual?".
  - Ofrece cupos y concreta la cita.
  
**FASE 4: PERFILAMIENTO (PUEDE SER AL FINAL)**
* Necesitamos saber:
  1. ¿Cuántos inmuebles tiene el conjunto?
  2. ¿El Fondo de Imprevistos supera los 45 millones?
* **MOMENTO DE PREGUNTAR:**
  - Si el usuario fluye hacia la cita, espera a tener la cita agendada.
  - Una vez confirmes la cita (o antes de despedirte), di: "Por cierto, para completar tu registro, ¿me confirmas estos dos datos?".

**FASE 5: CIERRE**
* Confirma correo, confirma fecha/hora y despídete.
"""

def analizar_contexto_unificado(user_message: str, history_text: str, fecha_contexto: str, email_actual: str, esperando_email: bool, project_id: str, location: str):
    # Inicializamos cliente Gemini aquí para que sea independiente
    client = genai.Client(vertexai=True, project=project_id, location=location)
    
    tz = pytz.timezone('America/Bogota')
    now = datetime.now(tz)
    dias_traduccion = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
    
    tabla_fechas = "REFERENCIA INTERNA DE CALENDARIO:\n"
    for i in range(0, 15):
        fecha_futura = now + timedelta(days=i)
        nombre_dia = dias_traduccion[fecha_futura.weekday()]
        fecha_str = fecha_futura.strftime('%Y-%m-%d')
        tabla_fechas += f"- {nombre_dia}: {fecha_str}\n"

    instrucciones_datos = """
    PAUTAS DE ANÁLISIS:
    1. DATOS COMPUESTOS (EJEMPLOS CLAVE):
       - Usuario: "tiene 5 inmuebles y si es mayor" -> "valor_inmuebles": 5, "respondio_fondo": true, "nivel_fondo": "mayor".
       - Usuario: "80 aptos y no alcanza" -> "valor_inmuebles": 80, "respondio_fondo": true, "nivel_fondo": "menor".

    2. DATOS DEL LEAD (FONDO DE IMPREVISTOS) - COMPARACIÓN MATEMÁTICA ESTRICTA:
       - PUNTO DE CORTE: 45 Millones de pesos.
       - MENOR (< 45M): Si dice "1 millón", "10 millones", "20.000.000", "44 millones" -> "nivel_fondo": "menor".
       - MAYOR (>= 45M): Si dice "45 millones", "50 millones", "100 millones" -> "nivel_fondo": "mayor".
       - TEXTO: "Si", "cumple", "es alto" -> "mayor". / "No", "es bajo", "no tiene" -> "menor".

    3. FECHAS Y HORAS (CRÍTICO):
       - "menciona_fecha": true SOLO si propone un DÍA distinto al actual o al del contexto.
       - "menciona_hora": true si propone una HORA o PREGUNTA DISPONIBILIDAD de una hora específica.
         * Ejemplos: "a las 11", "2 pm", "¿tienes a las 10?", "¿es posible a la 1?", "mira a ver a las 9".
       - "hora_simple": Extrae SOLO la hora en formato militar aproximado (ej: "11:00", "14:00", "09:30"). NO incluyas fecha.
    """

    prompt = f"""
    ANALIZA EL MENSAJE: "{user_message}"
    
    HISTORIAL RECIENTE:
    {history_text}
    
    CONTEXTO:
    - Hoy: {dias_traduccion[now.weekday()]} {now.strftime('%Y-%m-%d')}
    - Fecha Cita Activa: {fecha_contexto if fecha_contexto else "Ninguna"}
    
    {tabla_fechas}
    {instrucciones_datos}

    RETORNA SOLO ESTE JSON:
    {{
        "es_rechazo": (bool),
        "motivo_rechazo": (str o null),
        "datos_lead": {{
            "tiene_inmuebles": (bool),
            "valor_inmuebles": (int o null),
            "respondio_fondo": (bool),
            "nivel_fondo": ("mayor" / "menor" / null)
        }},
        "intencion_fecha": {{
            "menciona_fecha": (bool),
            "fecha_iso": (str YYYY-MM-DD),
            "nombre_dia": (str)
        }},
        "intencion_hora": {{
            "menciona_hora": (bool),
            "hora_simple": (str HH:MM)  
        }},
        "confirmacion_email": {{
            "es_confirmacion": (bool), 
            "nuevo_email": (str o null)
        }}
    }}
    """

    try:
        resp = client.models.generate_content(
            model="gemini-2.0-flash-lite-001", 
            contents=prompt, 
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
        )
        return limpiar_respuesta_json(resp.text)
    except Exception as e:
        print(f"⚠️ Error análisis unificado: {e}")
        return {}