# coding: utf-8
# Copyright (c) 2016, 2021, Oracle and/or its affiliates.  All rights reserved.

import oci
import uuid
import os
import json
import re
from datetime import datetime # [NOVO] Importado para pegar a data atual da extração

# Setup basic variables
CONFIG_PROFILE = "DEFAULT"
config = oci.config.from_file('./config', CONFIG_PROFILE)

# Compartment onde os Jobs serão criados
COMPARTMENT_ID = "ocid1.compartment.oc1............................................" 

def create_processor_job_callback(times_called, response):
    print("Waiting for processor lifecycle state to go into succeeded state:", response.data)

# Cliente Object Storage
object_storage_client = oci.object_storage.ObjectStorageClient(config)

# Definição do Alvo
bucket_name = "bucket-atlantic-origem"

namespace = object_storage_client.get_namespace().data
response = object_storage_client.list_objects(namespace, bucket_name)

aiservicedocument_client = oci.ai_document.AIServiceDocumentClientCompositeOperations(oci.ai_document.AIServiceDocumentClient(config=config))

# Para o LLM, precisamos apenas do texto bruto extraído via OCR
text_extraction_feature = oci.ai_document.models.DocumentTextExtractionFeature()

# Configuração do arquivo de entrada (Ajustado para o Boleto em JPEG)
object_location = oci.ai_document.models.ObjectLocation()
object_location.namespace_name = namespace
object_location.bucket_name = "bucket-atlantic-origem" 
object_location.object_name = "fatura_vivo_3.pdf" 

# Configuração do local de saída (Pastas temporárias do serviço de OCR)
output_location = oci.ai_document.models.OutputLocation()
output_location.namespace_name = namespace
output_location.bucket_name = "bucket-atlantic-destino" 
output_location.prefix = "boleto_destino" 

# Criação do Job
create_processor_job_details_text_extraction = oci.ai_document.models.CreateProcessorJobDetails(
    display_name=str(uuid.uuid4()),
    compartment_id=COMPARTMENT_ID,
    input_location=oci.ai_document.models.ObjectStorageLocations(object_locations=[object_location]),
    output_location=output_location,
    processor_config=oci.ai_document.models.GeneralProcessorConfig(features=[text_extraction_feature])
)

print("Enviando Job para o OCI Document Understanding...")
create_processor_response = aiservicedocument_client.create_processor_job_and_wait_for_state(
    create_processor_job_details=create_processor_job_details_text_extraction,
    wait_for_states=[oci.ai_document.models.ProcessorJob.LIFECYCLE_STATE_SUCCEEDED],
    waiter_kwargs={"wait_callback": create_processor_job_callback}
)

print("Job finalizado com status: {}.".format(create_processor_response.status))
processor_job = create_processor_response.data

# -------------------------------------------------------------------------
# Recuperação do Texto Bruto do OCI Document Understanding
# -------------------------------------------------------------------------

print("Baixando o resultado do Object Storage...")

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

conteudo_raw = get_object_response.data.content.decode('utf-8')
dados_json = json.loads(conteudo_raw)

# Extrai todo o texto do Boleto e junta em uma única string
texto_bruto_linhas = []
if 'pages' in dados_json:
    for page in dados_json['pages']:
        if 'lines' in page:
            for line in page['lines']:
                if 'text' in line:
                    texto_bruto_linhas.append(line['text'].strip())

payload_texto_ocr = "\n".join(texto_bruto_linhas)

# -------------------------------------------------------------------------
# Integração com OCI Generative AI (Llama 3)
# -------------------------------------------------------------------------

# Captura a data de hoje no formato DD/MM/AAAA para enviar ao LLM
data_atual_extracao = datetime.now().strftime("%d/%m/%Y")

print("Enviando dados extraídos para o OCI Generative AI (Llama)...")

# Cliente do OCI GenAI utilizando o Endpoint de São Paulo
generative_ai_inference_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
    config=config,
    service_endpoint="https://inference.generativeai.sa-saopaulo-1.oci.oraclecloud.com"
)

# Instruções otimizadas para o Llama com foco no Boleto Bancário
prompt_llama = f"""
Você é um assistente especializado em extração estruturada de dados financeiros e bancários brasileiros.
Abaixo está o texto bruto extraído de um BOLETO BANCÁRIO através de OCR.

INFORMAÇÃO DE SISTEMA: 
A "Data atual da extração" de hoje é: {data_atual_extracao}

Sua tarefa é encontrar as informações pertinentes do pagador/responsável, formatar os valores e retornar um arquivo JSON.
Você também deve comparar a "Data de vencimento" encontrada no boleto com a "Data atual da extração" e definir o status.

As chaves do seu JSON DEVEM ser exatamente estas:
- "Nome" (Nome do pagador/sacado)
- "Endereço" (Endereço completo do pagador, se houver)
- "Data de vencimento" (Formato DD/MM/AAAA)
- "Data atual da extração" (Preencha com a data de sistema fornecida acima)
- "Status do Boleto" (Preencha com "Vencido" se a data de vencimento for anterior à data atual, ou "No Prazo" se for igual ou posterior)

Regras estritas:
1. Retorne APENAS um objeto JSON válido contendo unicamente as chaves solicitadas. Não diga "Aqui está o JSON".
2. Não inclua blocos de formatação markdown (como ```json).
3. Não adicione NENHUMA explicação antes ou depois do JSON.
4. Se uma informação não for encontrada no texto, preencha o valor como "não encontrado".

TEXTO DO OCR:
{payload_texto_ocr}
"""

# Configuração da requisição (Chat) para o modelo Llama no OCI
chat_details = oci.generative_ai_inference.models.ChatDetails(
    compartment_id=COMPARTMENT_ID,
    serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
        model_id="ocid1.generativeaimodel.oc1.sa-saopaulo-1.amaaaaaask7dceyarsn4m6k3aqvvgatida3omyprlcs3alrwcuusblru4jaa"
    ),
    chat_request=oci.generative_ai_inference.models.GenericChatRequest(
        api_format="GENERIC",
        messages=[
            oci.generative_ai_inference.models.Message(
                role="USER",
                content=[
                    oci.generative_ai_inference.models.TextContent(text=prompt_llama)
                ]
            )
        ],
        max_tokens=400, 
        temperature=0.0, # Temperatura 0 para evitar alucinações de valores
        top_p=0.75
    )
)

try:
    # Executa a chamada para o OCI GenAI
    chat_response = generative_ai_inference_client.chat(chat_details)
    
    # Extrai a string de resposta do modelo
    resultado_llm_bruto = chat_response.data.chat_response.choices[0].message.content[0].text
    
    # Tratamento de segurança: Localiza apenas o que está entre { e }
    match = re.search(r'\{.*\}', resultado_llm_bruto, re.DOTALL)
    
    if match:
        resultado_json_limpo = match.group(0)
        json_extraido_final = json.loads(resultado_json_limpo)
        
        # Exibe o padrão definido para o Boleto
        print("\n--- JSON FINAL EXTRAÍDO PELO LLAMA (PADRÃO BOLETO) ---")
        print(json.dumps(json_extraido_final, ensure_ascii=False, indent=4))
        print("------------------------------------------------------")
        
        # -------------------------------------------------------------------------
        # Upload do JSON Limpo para a RAIZ do Bucket Destino
        # -------------------------------------------------------------------------
        nome_arquivo_final = "resultado_final_boleto.json" # Ficará na raiz do bucket
        
        print(f"\nSalvando o resultado final na raiz do bucket: {output_location.bucket_name} ...")
        
        # Converte o dicionário python limpo para string JSON
        conteudo_upload = json.dumps(json_extraido_final, ensure_ascii=False, indent=4)
        
        # Faz o upload diretamente pelo Object Storage Client
        object_storage_client.put_object(
            namespace_name=namespace,
            bucket_name=output_location.bucket_name,
            object_name=nome_arquivo_final,
            put_object_body=conteudo_upload.encode('utf-8')
        )
        print(f"Arquivo '{nome_arquivo_final}' salvo com sucesso na raiz do bucket!")
        
    else:
        print("\n[ERRO] O modelo não retornou um formato JSON identificável.")
        print("Saída bruta do modelo:\n", resultado_llm_bruto)

except Exception as e:
    print(f"\n[ERRO] Falha ao comunicar com o OCI Generative AI: {e}")
