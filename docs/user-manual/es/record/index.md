---
module: record
last_verified_commit: 0d60d45
---

# Expediente clínico

El expediente clínico del paciente, reunido en un solo lugar. Forma parte de
la app **Expediente clínico**.

## Pantallas

- [Configuración del Expediente clínico](./screens/settings_apps_clinical-record.md) — qué secciones lleva, en qué orden y qué puntos se revisan.

- El membrete de los documentos se configura en Espacio de trabajo:
  *Configuración → General → Membretes* y *Configuración → Cuenta → Mi
  membrete*.

## Dónde está

**Ficha del paciente → Expediente.** Muestra, en el orden de un expediente en
papel:

1. Identificación
2. Antecedentes: cuestionarios de salud, heredo-familiares, contexto médico, alergias, medicación, enfermedades
   sistémicas y antecedentes quirúrgicos
3. Odontograma: hallazgos y tratamientos, con sus dientes
4. Periodontogramas
5. Notas de evolución
6. Planes de tratamiento y recetas
7. Radiografías y fotografías
8. Consentimientos

Cada entrada lleva su fecha clínica (la de cuando ocurrió, no la de cuando se
capturó) y, cuando se conoce, el profesional responsable con su cédula.

La pestaña y el expediente impreso muestran la **normativa de referencia**
de la clínica, que se configura en *Configuración → General → Normativa del
expediente*.

## Qué debe tener el expediente

Arriba de la pestaña, una lista de diez puntos dice qué tiene ya el
expediente de este paciente y qué le falta: identificación completa,
motivo de consulta,
antecedentes heredo-familiares, antecedentes personales, odontograma,
diagnóstico, pronóstico, plan de tratamiento, notas de evolución y
consentimiento informado firmado.

- Comprueba que el dato **existe**, no que sea correcto.
- Si un punto sale pendiente, se completa donde se captura ese dato: los
  antecedentes en el historial médico, el diagnóstico y el pronóstico en
  el plan de tratamiento, el consentimiento en su pestaña.
- Es una lectura orientativa de la NOM-004-SSA3-2012, pendiente de
  revisión legal.

## Imprimir o entregar el expediente

*Imprimir o entregar* (arriba a la derecha) genera el expediente en PDF. El
expediente no sale de la clínica sin dejar constancia, así que antes se
indica:

- **Motivo de la entrega** y lo que ese motivo exige:
  - *Continuidad de la atención* (referencia o interconsulta): la
    justificación clínica.
  - *Copia para el paciente*: marcar que se comprobó su identidad.
  - *Tercero autorizado por el paciente* (aseguradora, segunda opinión):
    qué autorización firmó el paciente y hasta cuándo.
  - *Requerimiento de autoridad*: la autoridad y el número del
    requerimiento.
- **A quién se entrega.**
- **Qué se incluye**: se eligen las secciones. Las entradas anuladas nunca
  se incluyen.

Al confirmar se abre el PDF y la entrega queda en la sección *Entregas del
expediente*, con fecha, destinatario y motivo. Desde ahí, *Ver el documento
entregado* abre exactamente el PDF que se entregó, aunque el expediente haya
cambiado después. Una entrega no se edita ni se borra.

## Lo que conviene saber

- **La pantalla es de solo lectura.** Los datos se escriben donde siempre —el
  odontograma, las notas, el plan—; aquí se leen juntos. No hay dos copias.
- *Ocultar secciones vacías* viene activado; al apagarlo se ven todas, y
  una sección vacía dice que no hay nada registrado.
- *Mostrar anuladas* enseña las entradas que se retiraron. No se borran
  nunca: quedan marcadas.
- Las notas administrativas, los precios y los documentos administrativos
  no forman parte del expediente.

## Permisos

- `record.read`
- `record.disclose` — imprimir o entregar (administrador y dentista)

## Recursos técnicos

- [Resumen técnico](../../../technical/record/overview.md)
- [Permisos](../../../technical/record/permissions.md)
