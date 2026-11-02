<script setup lang="ts">
/** The way into Compras, contributed to the Existencias header. */
const { t } = useI18n()
</script>

<template>
  <UButton
    variant="ghost"
    icon="i-lucide-shopping-cart"
    :label="t('purchasing.orders.open')"
    to="/inventario/compras"
  />
</template>
