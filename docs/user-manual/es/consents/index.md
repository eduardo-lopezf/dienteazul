---
module: consents
last_verified_commit: 0d60d45
---

# Consentimientos

Las cartas de consentimiento del paciente. Forma parte de la app **Expediente
clínico**.

## Qué hace

- **Consentimiento informado.** La carta en la que un profesional explica al
  paciente un procedimiento, sus riesgos y sus alternativas, y el paciente
  acepta o no. No se puede firmar sin indicar qué profesional lo explicó.
- **Uso de datos personales.** El paciente acepta el aviso de privacidad de
  la clínica.

## Dónde está

- **Ficha del paciente → Consentimientos.** Lista las cartas del paciente.
  *Nuevo consentimiento* crea un borrador a partir de una plantilla;
  *Firmar* muestra el texto al paciente y recoge su firma (o registra que
  no acepta). *Imprimir* abre la carta en PDF.
- **Configuración → Clínica → Plantillas de consentimiento.** Los textos de la
  clínica: uno por procedimiento, y el aviso de privacidad. Editar una
  plantilla crea una versión nueva; las cartas ya escritas no cambian.

## Dos formas de firmar

- **En pantalla.** El paciente firma con el dedo, el lápiz o el ratón.
- **En papel.** En *Firmar* elige *En papel* y pulsa *Imprimir*: la carta
  sale con los datos del paciente y el texto ya escritos, y con líneas
  para llenar a mano el diagnóstico, el plan de tratamiento, el lugar y la
  fecha, y las firmas del paciente o responsable, de quien informó y de
  dos testigos. Una vez firmada, escanéala o fotografíala, súbela en
  *Carta firmada escaneada* (PDF, JPG o PNG) y pulsa *Guardar carta
  firmada*. El archivo queda en los documentos del paciente y la carta
  pasa a **Firmado**, marcada como *Firmado en papel*; el botón *Escaneo*
  la abre.

## Consentimiento antes de confirmar un plan

La carta no es obligatoria: la regla viene apagada. Si la clínica la
activa, un plan de tratamiento no se confirma sin una carta de
consentimiento informado firmada y escrita para ese plan, y al marcar un
tratamiento como realizado o finalizar una cita de ese plan se pregunta
antes por la carta.

- Desde el plan, *Confirmar* avisa de que falta y **Crear la carta** abre
  esta pestaña para ese plan. La carta que se guarda queda marcada *De un
  plan*.
- Cuenta solo una carta de **consentimiento informado**, **firmada** (en
  pantalla o en papel) y no revocada. Una carta de otro plan, o el
  consentimiento de uso de datos, no la sustituyen.
- Se apaga con el interruptor *Exigir consentimiento informado para
  confirmar un plan*, en *Configuración → Clínica → Plantillas de
  consentimiento*.

## Lo que conviene saber

- Sin el escaneo, una carta en papel no se puede marcar como firmada: el
  escaneo es la firma que guarda el expediente.

- Un borrador se puede editar o descartar. **Una carta firmada no se edita
  ni se borra**: si el paciente retira su consentimiento, se **revoca**, y
  queda constancia de lo que firmó y de cuándo lo retiró.
- Las cartas firmadas, las no aceptadas y las revocadas aparecen en el
  expediente clínico del paciente.
- El texto de las plantillas es responsabilidad de la clínica y de su asesor
  legal; el programa no trae redacción legal.
- Con la app Profesionales deshabilitada no se puede indicar quién explicó
  el procedimiento, así que no se puede firmar un consentimiento informado.

## Permisos

- `consents.read`
- `consents.write`
- `consents.templates.write`

## Recursos técnicos

- [Resumen técnico](../../../technical/consents/overview.md)
- [Permisos](../../../technical/consents/permissions.md)
