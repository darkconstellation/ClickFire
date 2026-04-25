# Pake image Python yang slim biar gak menuhin RAM Orion lu, walau RAM lu 96GB tetep aja jancuk!
FROM python:3.11-slim

# Set working directory di dalem container
WORKDIR /app

# Copas requirements dulu biar ke-cache sama Docker
COPY requirements.txt .

# Install dependencies (termasuk FastAPI, Uvicorn, Motor, dll)
RUN pip install --no-cache-dir -r requirements.txt

# Copas semua code ClickFire lu ke dalem container
COPY . .

# Expose port buat FastAPI
EXPOSE 18000

# Jalanin Uvicorn server-nya
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18000"]