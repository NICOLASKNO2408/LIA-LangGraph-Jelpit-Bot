# 🤖 LIA: Agente de Ventas Inteligente con LangGraph & Gemini

LIA (Logística Inteligente de Agendamiento) es un asistente conversacional avanzado diseñado para automatizar el ciclo de ventas y agendamiento de **Jelpit Conjuntos (Davivienda)**. Utiliza un motor de estados basado en grafos para gestionar conversaciones complejas, perfilar leads y coordinar citas en tiempo real.

## 🚀 Características Principales

* **Motor de Estados con LangGraph**: Gestión de flujos no lineales que incluyen agendamiento, re-agendamiento, manejo de objeciones y perfilamiento.
* **Inteligencia Artificial con Gemini 2.0 Flash**: Análisis de contexto unificado para extracción de entidades como fechas (ISO), horas (formato militar) y correos electrónicos mediante Regex y LLM.
* **Estrategia de "Vida Extra"**: Sistema de recuperación que detecta la primera negativa del usuario y aplica técnicas de persuasión basadas en la "Experiencia Jelpit" antes de finalizar la sesión.
* **Integraciones Blindadas (Tools)**:
    * **Google Calendar API**: Verificación de disponibilidad real por asesor, manejo de festivos en Colombia y creación de eventos con Google Meet.
    * **Google Sheets API**: Registro automatizado de leads interesados, motivos de rechazo y actualización de datos de re-agendamiento.
    * **Firestore**: Persistencia del estado de la conversación para sesiones multi-turno y recuperación de historial.

## 🛠️ Arquitectura del Sistema

El proyecto está estructurado en módulos especializados para garantizar escalabilidad:

1.  **`graph.py`**: Define el flujo de trabajo (`StateGraph`). Contiene los nodos de **Análisis** (NLU), **Lógica de Negocio** (validaciones y toma de decisiones) y **Generación** (LLM).
2.  **`main.py`**: API desarrollada en FastAPI que expone endpoints para iniciar chats, procesar mensajes, validar Habeas Data y gestionar re-agendamientos.
3.  **`utils.py`**: El "cerebro" analítico. Contiene las instrucciones de sistema blindadas y la lógica de extracción de JSON estructurado para Gemini.
4.  **`tools.py`**: Capa de servicios para la interacción con las APIs de Google y lógica de asignación de asesores.
5.  **`state.py`**: Definición del esquema de datos (`LiaState`) que viaja a través del grafo.

## 📋 Requisitos Previos

* Python 3.10+
* Cuenta de Google Cloud Platform (GCP) con **Vertex AI** habilitado.
* Archivo `service_account.json` con permisos para Sheets, Calendar y Firestore.
* Archivo `token.json` (OAuth2) para la gestión de calendarios de asesores.

## 🔧 Configuración e Instalación

1.  **Clonar el repositorio**:
    ```bash
    git clone [https://github.com/tu-usuario/lia-langgraph.git](https://github.com/tu-usuario/lia-langgraph.git)
    cd lia-langgraph
    ```

2.  **Instalar dependencias**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Variables de Entorno**:
    Crea un archivo `.env` con las siguientes variables:
    ```env
    GCP_PROJECT_ID=tu-proyecto-id
    GCP_LOCATION=us-central1
    PORT=8080
    ```

## 🚦 Endpoints de la API

* `POST /chat/start`: Inicia una nueva sesión con datos del lead y el contexto inicial (Interesado/No interesado).
* `POST /chat/message`: Endpoint principal para la interacción continua del chat.
* `POST /chat/reschedule`: Permite a un usuario existente cambiar la fecha de su cita mediante su ID de registro.
* `POST /chat/validate-habeas`: Valida la autorización de tratamiento de datos ("AUTORIZO" / "NO AUTORIZO").

## 🛡️ Lógica de Negocio y Persuasión

El agente no acepta un "no" por respuesta a la primera. Si el análisis detecta un rechazo, el sistema verifica la bandera `recuperacion_aplicada`. Si es `False`, activa un script de mercadeo que destaca:
* Tarifas especiales y descuentos.
* Portal transaccional gratuito.
* Acceso a la plataforma Jelpit sin costo adicional.

---
**Desarrollado para la optimización de Propiedad Horizontal con tecnología de Google Cloud.**