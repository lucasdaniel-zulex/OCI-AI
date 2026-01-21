# coding: utf-8
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.

import oci
import os
import json

# --- CONFIGURAÇÕES GERAIS ---

# Auth Config
# TODO: Atualize o profile e o compartmentId conforme necessário
compartment_id = "ocid1.compartment.oc1..aaaaaaaa3yuokzmsm34nyvph6sca7bprskcir42w3vlpoiwf5x5nx35riu3a"
CONFIG_PROFILE = "DEFAULT"
config = oci.config.from_file('./config', CONFIG_PROFILE)

# Service endpoint GenAI
endpoint = "https://inference.generativeai.sa-saopaulo-1.oci.oraclecloud.com"

# --- CLIENTES OCI ---

# Cliente GenAI
generative_ai_inference_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
    config=config, 
    service_endpoint=endpoint, 
    retry_strategy=oci.retry.NoneRetryStrategy(), 
    timeout=(10,240)
)

# [NOVO] Cliente Object Storage
object_storage_client = oci.object_storage.ObjectStorageClient(config)

# --- LEITURA DO ARQUIVO JSON DO BUCKET ---

# [NOVO] Configurações do Object Storage
bucket_name = "Bucket-Destino"   # <--- Coloque o nome do seu bucket aqui
object_name = "resultado/ocid1.aidocumentprocessorjob.oc1.sa-saopaulo-1.amaaaaaafioir7iasdriv755y2ixf6mqybjyy7cdhinemh7223ydf4zkbviq/idi1o0a010nx_Bucket-Origem/results/doctest.pdf.json"       # <--- O nome do arquivo dentro do bucket

print(f"Buscando arquivo '{object_name}' no bucket '{bucket_name}'...")

try:
    # 1. Obtém o Namespace (necessário para fazer a chamada ao bucket)
    namespace = object_storage_client.get_namespace().data

    # 2. Busca o objeto no Object Storage
    response = object_storage_client.get_object(namespace, bucket_name, object_name)
    
    # 3. Lê o conteúdo do arquivo (stream de bytes) e decodifica
    file_content = response.data.content.decode('utf-8')
    
    # 4. Carrega como JSON
    dados_json = json.loads(file_content)
    
    # Converte o objeto JSON de volta para string para enviar no prompt
    json_string = json.dumps(dados_json, indent=2, ensure_ascii=False)
    print("Arquivo JSON recuperado e processado com sucesso.")

except oci.exceptions.ServiceError as e:
    print(f"Erro de Serviço OCI (verifique permissões ou se o arquivo existe): {e}")
    exit()
except json.JSONDecodeError:
    print(f"Erro: O arquivo '{object_name}' no bucket não contém um JSON válido.")
    exit()
except Exception as e:
    print(f"Erro inesperado ao ler do bucket: {e}")
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
chat_request.temperature = 0.5
chat_request.frequency_penalty = 0
chat_request.presence_penalty = 0
chat_request.top_p = 0.75

# ID do Modelo
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
    
    choices = chat_response.data.chat_response.choices
    if choices:
        texto_resposta = choices[0].message.content[0].text
        print(texto_resposta)
    else:
        print("Nenhuma resposta gerada.")

except Exception as e:
    print(f"Ocorreu um erro na chamada da API GenAI: {e}")
