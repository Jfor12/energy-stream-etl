# 1. Base Image: Use a lightweight Python setup
FROM python:3.9-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Copy all your project files into the container
COPY . .

# 4. Install dependencies
# (Ensure requirements.txt exists in the same folder!)
RUN pip install --no-cache-dir -r requirements.txt

# 5. Expose the port (Cloud Run expects 8080 by default)
EXPOSE 8080

# 6. The Command to run the app
# We tell Streamlit to run on port 8080 and listen to all external connections (0.0.0.0)
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]