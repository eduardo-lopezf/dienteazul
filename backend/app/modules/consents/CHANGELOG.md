# Changelog — consents module

## Unreleased

- change(consents): la regla «exigir consentimiento informado para
  confirmar un plan» viene **apagada**. La carta no es obligatoria hasta
  que la clínica active el interruptor; con él apagado nada bloquea ni
  pregunta (ni al confirmar un plan, ni al marcar un tratamiento como
  realizado, ni al finalizar una cita).

- refactor(consents): el método del contrato `PlanConsents` pasa a
  llamarse `lacks_required_consent`: ya no responde solo a «¿se puede
  confirmar?», también a «¿falta la carta de un plan en curso?».

- feat(consents): **un plan de tratamiento espera su consentimiento
  informado**. La clínica exige, por defecto, que el paciente firme una
  carta de consentimiento informado escrita para el plan antes de
  confirmarlo. Cuenta una carta `informed`, firmada, ligada a ese plan y
  no revocada.
  - La regla es de este módulo: la ofrece a Tratamientos por el contrato
    `PlanConsents` (ADR 0039), que solo obedece.
  - Se apaga en *Configuración → Clínica → Plantillas de consentimiento*
    (`GET/PUT /consents/settings`, `require_informed_for_plan`).
  - Con la app Profesionales apagada no se exige: un consentimiento
    informado no se puede firmar sin nombrar quién lo explicó.
  - La pestaña *Consentimientos* acepta `?plan=<id>`: la carta que se
    escribe queda ligada al plan, se marca *De un plan* y, una vez
    firmada, ofrece volver a él.

- refactor(consents): el lienzo de firma (`SignaturePad`) pasa al núcleo
  (`frontend/app/components/shared/`), porque el cuestionario de salud de
  Pacientes también firma. Sin cambios en la firma de cartas.

- fix(consents): cargas de escaneos y aperturas de documentos usan el transporte BFF autenticado con cookie HttpOnly.
- feat(consents): la carta impresa lleva el **membrete del profesional
  que la explicó** o, si no tiene uno propio, el de la clínica — nunca el
  de otro doctor (`app.core.letterhead`, ADR 0046). Bajo el membrete sale
  el profesional que informa, con su cédula; antes encabezaba la hoja.

- feat(consents): tipo de carta nuevo, **conformidad con el tratamiento**
  (`conformity`): el paciente firma que el tratamiento se concluyó a su
  satisfacción — la *firma de conformidad* de la historia en papel. No
  exige nombrar a un profesional y no sustituye al consentimiento
  informado. No comprueba que no haya adeudo.

- feat(consents): **firma en papel**. Una carta se puede imprimir, llenar
  y firmar a mano, y después subir escaneada.
  - `GET /{id}/pdf`: la carta como hoja para imprimir. En borrador es un
    formulario: los datos del paciente y el texto ya vienen escritos, y el
    diagnóstico, el plan, los nombres, las fechas y las firmas (paciente o
    responsable, quien informó y dos testigos) son líneas para llenar a
    mano. Una carta firmada en pantalla se imprime con su firma.
  - `POST /{id}/sign` acepta `method: "paper"` con `document_id`: el
    escaneo, ya subido a los documentos del paciente. Se comprueba, a
    través del contrato `PatientDocuments`, que el archivo es de ese mismo
    paciente. La carta guarda `signature_method` (`screen` | `paper`).
  - Pantalla de firma: selector *En pantalla / En papel*; en papel, botón
    *Imprimir* y campo para subir el escaneo (PDF, JPG o PNG). En la lista,
    *Imprimir* en cada carta y *Escaneo* en las firmadas en papel.
  - `integrates` añade `media`: con Media apagado se puede imprimir y
    firmar en pantalla, pero no archivar un escaneo.
  - Migración `con_0002`: columna `signature_method`; las cartas ya
    firmadas quedan como `screen`.

- feat(consents): módulo nuevo, dentro de la App **Expediente clínico**.
  Cartas de consentimiento del paciente, en dos tipos: **consentimiento
  informado** (NOM-004-SSA3-2012; Ley General de Salud Art. 51 Bis 1) y
  **uso de datos personales** (aviso de privacidad).
  - Plantillas de la clínica con versión; cada carta guarda su propia
    copia del texto y la versión de la plantilla.
  - Borrador → firmado / no aceptado; firmado → revocado. Una carta
    firmada no se edita ni se borra (ADR 0032, ADR 0045).
  - Un consentimiento informado no se puede firmar sin indicar qué
    profesional lo explicó; se guarda su nombre y cédula de ese día.
  - Firma en pantalla (tableta, ratón o lápiz).
  - Pestaña *Consentimientos* en la ficha del paciente y página
    *Plantillas de consentimiento* en Configuración → Clínica.
  - Las cartas firmadas, no aceptadas y revocadas forman parte del
    expediente clínico compuesto (sección `consents`).
  - Derechos del paciente: se exportan; no se suprimen.
