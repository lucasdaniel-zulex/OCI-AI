# coding: utf-8
# Copyright (c) 2016, 2021, Oracle and/or its affiliates.  All rights reserved.

import oci
import uuid
import base64
import os
import json

# =========================================================================
# 1. CONFIGURAÇÃO INICIAL E AUTENTICAÇÃO
# =========================================================================

CONFIG_PROFILE = "DEFAULT"
config = oci.config.from_file('./config', CONFIG_PROFILE)

# Compartment onde o Job será criado
COMPARTMENT_ID = "ocid1.compartment.oc1..aaaaaaaa3yuokzmsm34nyvph6sca7bprskcir42w.........." 

# Definição dos Buckets
BUCKET_ORIGEM = "Bucket-Origem"
BUCKET_DESTINO = "Bucket-Destino"
ARQUIVO_ALVO = "Modelo_Manuscrito_reduzido_test.pdf"

# Clients
object_storage_client = oci.object_storage.ObjectStorageClient(config)
aiservicedocument_client = oci.ai_document.AIServiceDocumentClientCompositeOperations(
    oci.ai_document.AIServiceDocumentClient(config=config)
)

# Obtém Namespace
namespace = object_storage_client.get_namespace().data

# =========================================================================
# 2. DOCUMENT UNDERSTANDING: EXTRAÇÃO DO TEXTO (OCR)
# =========================================================================

print(f"--- Iniciando processamento do arquivo: {ARQUIVO_ALVO} ---")

# Configuração do Job
text_extraction_feature = oci.ai_document.models.DocumentTextExtractionFeature()

object_location = oci.ai_document.models.ObjectLocation()
object_location.namespace_name = namespace
object_location.bucket_name = BUCKET_ORIGEM
object_location.object_name = ARQUIVO_ALVO

output_location = oci.ai_document.models.OutputLocation()
output_location.namespace_name = namespace
output_location.bucket_name = BUCKET_DESTINO
output_location.prefix = "resultado_NPI"

create_processor_job_details = oci.ai_document.models.CreateProcessorJobDetails(
    display_name=str(uuid.uuid4()),
    compartment_id=COMPARTMENT_ID,
    input_location=oci.ai_document.models.ObjectStorageLocations(object_locations=[object_location]),
    output_location=output_location,
    processor_config=oci.ai_document.models.GeneralProcessorConfig(features=[text_extraction_feature])
)

def create_processor_job_callback(times_called, response):
    print(f"Aguardando Document Understanding... Status: {response.data.lifecycle_state}")

print("Enviando Job para o OCI Document Understanding...")
create_processor_response = aiservicedocument_client.create_processor_job_and_wait_for_state(
    create_processor_job_details=create_processor_job_details,
    wait_for_states=[oci.ai_document.models.ProcessorJob.LIFECYCLE_STATE_SUCCEEDED],
    waiter_kwargs={"wait_callback": create_processor_job_callback}
)

print("OCR concluído com sucesso.")
processor_job = create_processor_response.data

# =========================================================================
# 3. LIMPEZA DE DADOS (PYTHON PROCESSING)
# =========================================================================

print("Baixando e limpando o JSON resultante...")

nome_objeto_resultado = "{}/{}/{}_{}/results/{}.json".format(
    output_location.prefix, 
    processor_job.id,
    object_location.namespace_name,
    object_location.bucket_name,
    object_location.object_name
)

get_object_response = object_storage_client.get_object(
    namespace_name=output_location.namespace_name,
    bucket_name=output_location.bucket_name,
    object_name=nome_objeto_resultado
)

# Decodifica e carrega JSON
conteudo_raw = get_object_response.data.content.decode('utf-8')
dados_json = json.loads(conteudo_raw)

# Filtra apenas o texto das linhas
texto_limpo_lista = []
if 'pages' in dados_json:
    for page in dados_json['pages']:
        if 'lines' in page:
            for line in page['lines']:
                if 'text' in line:
                    texto_limpo_lista.append(line['text'])

# Cria a string final limpa
texto_final_para_llm = "\n".join(texto_limpo_lista)

print(f"Texto extraído (bruto limpo): {len(texto_final_para_llm)} caracteres.")

# =========================================================================
# 4. GENERATIVE AI: CORREÇÃO E INTERPRETAÇÃO
# =========================================================================

endpoint = "https://inference.generativeai.sa-saopaulo-1.oci.oraclecloud.com"

generative_ai_inference_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
    config=config, 
    service_endpoint=endpoint, 
    retry_strategy=oci.retry.NoneRetryStrategy(), 
    timeout=(10,240)
)

# Prompt otimizado para correção mantendo fidelidade
prompt_usuario = f"""
Você é um especialista em transcrição de documentos manuscritos.
Tarefa: Abaixo está um texto bruto extraído via OCR de um documento manuscrito. Ele contém quebras de linha e possíveis erros de reconhecimento de caracteres.
Ação: Reescreva o texto corrigindo a gramática e a pontuação para torná-lo fluido e legível.
Restrição Importante: Mantenha estritamente o sentido original e todas as informações factuais (datas, nomes, valores). Não adicione informações que não estão no texto.

Texto OCR Bruto:
\"\"\"
{texto_final_para_llm}
\"\"\"

Texto Corrigido:
"""

# Configuração da chamada de Chat
chat_detail = oci.generative_ai_inference.models.ChatDetails()
content = oci.generative_ai_inference.models.TextContent()
content.text = prompt_usuario

message = oci.generative_ai_inference.models.Message()
message.role = "USER"
message.content = [content]

chat_request = oci.generative_ai_inference.models.GenericChatRequest()
chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
chat_request.messages = [message]
chat_request.max_tokens = 1000 # Aumentei um pouco para garantir resposta completa
chat_request.temperature = 0.2 # Baixa temperatura para ser mais fiel/determinístico
chat_request.top_p = 0.75

# Modelo Llama 3 (usando o ID fornecido no seu código)
chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(
    model_id="ocid1.generativeaimodel.oc1.sa-saopaulo-1.amaaaaaask7dceyarsn4m6k3aqvvgatida3omyprlcs3a......."
)
chat_detail.chat_request = chat_request
chat_detail.compartment_id = COMPARTMENT_ID # Usando a constante unificada

print("\n--- Enviando para OCI Generative AI (Llama 3) ---")
try:
    chat_response = generative_ai_inference_client.chat(chat_detail)
    
    print("\n************************** MANUSCRITO INTERPRETADO **************************")
    
    choices = chat_response.data.chat_response.choices
    if choices:
        texto_resposta = choices[0].message.content[0].text
        print(texto_resposta)
    else:
        print("Nenhuma resposta gerada pelo modelo.")

except Exception as e:
    print(f"Erro na chamada da API GenAI: {e}")
