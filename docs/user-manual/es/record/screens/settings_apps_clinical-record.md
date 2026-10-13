---
module: record
screen: settings_apps_clinical-record
route: /settings/apps/clinical-record
related_endpoints:
  - GET /api/v1/record/format
  - PUT /api/v1/record/format
related_permissions:
  - record.read
  - record.configure
  - admin.clinic.read
  - admin.clinic.write
related_paths:
  - backend/app/modules/record/frontend/pages/settings/apps/clinical-record.vue
last_verified_commit: f9ad75a
---

# Configuración del Expediente clínico

**Configuración → Apps → Expediente clínico → Configurar.** Cómo se arma el
expediente clínico en esta clínica. Lo que se elige aquí aplica a toda la
clínica, en la pestaña *Expediente* de cada paciente y en el documento que
se imprime o entrega.

## Permisos

- `record.read` — ver el formato.
- `record.configure` — cambiarlo (solo administrador).

## Membretes

El membrete de los documentos ya no se configura aquí: está en
**Configuración → General → Membretes**, porque encabeza los documentos de
todas las apps y debe poder editarse aunque Expediente clínico esté
deshabilitado. Cada profesional sigue teniendo el suyo en *Configuración →
Cuenta → Mi membrete*.

## Secciones y orden

Cada sección del expediente tiene un interruptor y flechas para subir o
bajar.

- **Apagar una sección** la quita de la pestaña *Expediente* y de lo que se
  puede imprimir o entregar. **No borra nada**: los datos siguen donde se
  capturan, y al encenderla vuelve a aparecer.
- **El orden** es el que sigue el expediente en pantalla y en papel.
- Una sección que añada una app habilitada después aparece al final.

## Qué debe tener el expediente

Los puntos que la pestaña *Expediente* revisa en cada paciente. Apaga los
que no apliquen a tu clínica; dejarán de mostrarse como pendientes.

## Plantillas de consentimiento

Acceso directo a los textos de las cartas de consentimiento.

## Guardar y restablecer

Nada cambia hasta pulsar **Guardar**. **Restablecer** vuelve al formato por
defecto —todas las secciones, en el orden de un expediente en papel, todos
los puntos revisados— y también hay que guardarlo.
