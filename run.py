import uvicorn
import os

if __name__ == "__main__":
    host = os.getenv("JOBPILOT_HOST", "127.0.0.1")
    port = int(os.getenv("JOBPILOT_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
