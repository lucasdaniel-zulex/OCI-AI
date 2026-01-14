import oci
import os
import json

# Setup basic variables
# Auth Config
# TODO: Please update config profile name and use the compartmentId that has policies grant permissions for using Generative AI Service
compartment_id = "ocid1.compartment.oc1..aaaaaaaa3yuokzmsm34nyvph6sca7bprskcir42w3vlpoiwf5x5nx35riu3a"
CONFIG_PROFILE = "DEFAULT"
config = oci.config.from_file('./config', "DEFAULT")

# Service endpoint
endpoint = "https://inference.generativeai.sa-saopaulo-1.oci.oraclecloud.com"

generative_ai_inference_client = oci.generative_ai_inference.GenerativeAiInferenceClient(config=config, service_endpoint=endpoint, retry_strategy=oci.retry.NoneRetryStrategy(), timeout=(10,240))

# --- LEITURA DO ARQUIVO JSON ---

nome_arquivo = 'resultado.json' # Certifique-se de que este arquivo existe no mesmo diretório ou passe o caminho completo

try:
    if not os.path.exists(nome_arquivo):
        print(f"Erro: O arquivo '{nome_arquivo}' não foi encontrado.")
        exit()

    with open(nome_arquivo, 'r', encoding='utf-8') as f:
        dados_json = json.load(f)
        # Converte o objeto JSON de volta para string para enviar no prompt
        json_string = json.dumps(dados_json, indent=2, ensure_ascii=False)

except json.JSONDecodeError:
    print(f"Erro: O arquivo '{nome_arquivo}' não contém um JSON válido.")
    exit()
except Exception as e:
    print(f"Erro ao ler o arquivo: {e}")
    exit()

# --- PREPARAÇÃO DO PROMPT ---

prompt_usuario = f"""
Você é um assistente de IA especialista em análise de dados.
Abaixo está um conteúdo em formato JSON. Por favor, analise-o e forneça um resumo claro e conciso das principais informações contidas nele.

JSON:
{json_string}
"""

# --- CONFIGURAÇÃO DA REQUISIÇÃO AO OCI GENAI ---

chat_detail = oci.generative_ai_inference.models.ChatDetails()

content = oci.generative_ai_inference.models.TextContent()
content.text = prompt_usuario

message = oci.generative_ai_inference.models.Message()
message.role = "USER"
message.content = [content]

chat_request = oci.generative_ai_inference.models.GenericChatRequest()
chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
chat_request.messages = [message]
chat_request.max_tokens = 600
chat_request.temperature = 0.5 # Reduzi um pouco a temperatura para o resumo ser mais focado
chat_request.frequency_penalty = 0
chat_request.presence_penalty = 0
chat_request.top_p = 0.75

# ID do Modelo (Llama 3 70B Instruct ou similar conforme seu código original)
chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(
    model_id="ocid1.generativeaimodel.oc1.sa-saopaulo-1.amaaaaaask7dceyarsn4m6k3aqvvgatida3omyprlcs3alrwcuusblru4jaa"
)
chat_detail.chat_request = chat_request
chat_detail.compartment_id = compartment_id

# --- EXECUÇÃO ---

print("Enviando requisição para o modelo Llama...")
try:
    chat_response = generative_ai_inference_client.chat(chat_detail)
    
    print("\n************************** RESUMO DO JSON **************************")
    
    # Extraindo o texto da resposta (Navegação baseada na estrutura do GenericChatResponse)
    # A estrutura pode variar levemente dependendo da versão do SDK, mas geralmente é:
    choices = chat_response.data.chat_response.choices
    if choices:
        texto_resposta = choices[0].message.content[0].text
        print(texto_resposta)
    else:
        print("Nenhuma resposta gerada.")

    # Se quiser ver o objeto bruto para debug, descomente a linha abaixo:
    # print("\nRaw Response:", vars(chat_response))

except Exception as e:
    print(f"Ocorreu um erro na chamada da API: {e}")
