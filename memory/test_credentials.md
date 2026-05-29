# Test Credentials

## Admin Panel
- Password: `papersumo2025`
- Auth: POST `/api/admin/login` with `{"password":"papersumo2025"}` returns `{"token": "..."}`
- Use token via `x-admin-token` header on admin endpoints
