from http.server import HTTPServer, SimpleHTTPRequestHandler
import json

class API_Jarvis(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        # O Passe Livre para a Extensão do Chrome
        self.send_header('Access-Control-Allow-Origin', '*') 
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        try:
            with open('dados_jarvis.json', 'r', encoding='utf-8') as f:
                self.wfile.write(f.read().encode('utf-8'))
        except FileNotFoundError:
            self.wfile.write(b'{"erro": "Arquivo dados_jarvis.json ainda nao foi criado pelo Streamlit."}')

print("🟢 Servidor da Extensão Jarvis rodando na porta 8000...")
print("Não feche este terminal!")
HTTPServer(('localhost', 8000), API_Jarvis).serve_forever()