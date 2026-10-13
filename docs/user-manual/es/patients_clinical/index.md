---
module: patients_clinical
last_verified_commit: 0000000
---

# Patients Clinical

> _Esqueleto generado automáticamente — reemplazar con documentación real cuando se toque este módulo._

Página de aterrizaje del módulo `patients_clinical` en el manual de usuario.

## Cuestionario de salud

**Ficha del paciente → Cuestionario de salud.** Lo que el paciente declara
en su consulta: motivo de consulta, grupo sanguíneo, alergias, doce
preguntas de sí o no (con su causa) y la lista de padecimientos.

- **En pantalla:** *Nuevo cuestionario*. Una pregunta que se deja sin
  contestar queda como no preguntada, no como «no».
- **Firma:** al final del formulario en pantalla, el paciente firma con el
  dedo, un lápiz o el ratón. Se propone su nombre; si firma un tutor o un
  representante, se cambia el nombre y se indica en *Firma como*. La firma
  es obligatoria para guardar; la lista marca con *Firmado* los que la
  llevan y al abrir uno se ve la firma y quién firmó. Si el paciente
  prefiere firmar a mano, se usa *En papel*: las dos formas valen igual.
- **En papel:** *Imprimir en blanco* saca la hoja con los datos del
  paciente; se llena a mano, se escanea y se sube desde *Nuevo
  cuestionario → En papel*. El motivo de consulta se escribe aparte para
  que aparezca en el expediente.
- Un cuestionario guardado no se edita: en la siguiente visita se llena
  otro. Si se guardó por error, *Anular* lo retira dejando constancia.
- No sustituye al historial médico: las alergias, la medicación y las
  enfermedades que la clínica mantiene al día siguen en su sitio.
- Al pie del formulario, y encima de la firma en la hoja en blanco, aparece
  la **normativa de referencia** de la clínica (*Configuración → General →
  Normativa del expediente*).

## Clasificación ASA

**Ficha del paciente → Resumen → Clasificación ASA.** El estado físico del
paciente según la escala ASA, tal como lo valoró un clínico en una fecha.

- La tarjeta muestra la clase vigente, cuándo se valoró y quién.
- *Valorar* abre el diálogo: se elige la clase (I a IV), se marca si es un
  procedimiento de urgencia (modificador E) y se anota en qué se basa.
- Una valoración no se edita. Si el estado del paciente cambia, se valora
  de nuevo: la anterior queda en el historial. Si se guardó por error,
  *Anular* la retira dejando constancia, y la anterior vuelve a ser la
  vigente.
- Una clase III o superior aparece entre las alertas de la ficha, junto a
  las alergias.
- Al **agendar una cita**, la ventana avisa si el paciente es ASA III o IV,
  con la fecha de la valoración y en qué se basa. No impide guardar la
  cita. Recepción ve solo la clase («ASA IV») y la recomendación; lo que
  significa, cuándo se valoró, quién y en qué se basa solo lo ve quien
  puede leer el historial médico.
- Valorar requiere el permiso `patients_clinical.asa.write` (dentistas y
  administradores). Quien solo puede leer el historial ve la clase y su
  historial.

## Pantallas

Este módulo no aporta páginas Nuxt propias.

## Permisos

- `patients_clinical.medical.read`
- `patients_clinical.medical.write`
- `patients_clinical.asa.read`
- `patients_clinical.asa.write`
- `patients_clinical.emergency.read`
- `patients_clinical.emergency.write`

## Recursos técnicos

- [Resumen técnico](../../../technical/patients_clinical/overview.md)
- [Permisos](../../../technical/patients_clinical/permissions.md)
- [Eventos](../../../technical/patients_clinical/events.md)
