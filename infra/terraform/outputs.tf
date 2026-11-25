output "function_app" {
  value = azurerm_linux_function_app.fn.name
}

output "upload_container" {
  value = "${azurerm_storage_account.sa.primary_blob_endpoint}${azurerm_storage_container.invoices.name}"
}
