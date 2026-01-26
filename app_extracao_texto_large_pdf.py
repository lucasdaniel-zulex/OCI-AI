# coding: utf-8
# Copyright (c) 2016, 2021, Oracle and/or its affiliates.  All rights reserved.

import oci
import uuid
import json
import re
import time
from difflib import SequenceMatcher

# =========================================================================
# 1. CONFIGURAÇÃO
# =========================================================================

CONFIG_PROFILE = "DEFAULT"
config = oci.config.from_file('./config', CONFIG_PROFILE)
COMPARTMENT_ID = "ocid1.compartment.oc1..aaaaaaaa3yuokzmsm34nyvph6sca7b......................." 
BUCKET_ORIGEM = "Bucket-Origem"
BUCKET_DESTINO = "Bucket-Destino"
ARQUIVO_ALVO = "Modelo_Manuscrito_reduz..........."

# Clients
object_storage_client = oci.object_storage.ObjectStorageClient(config)
aiservicedocument_client = oci.ai_document.AIServiceDocumentClientCompositeOperations(
    oci.ai_document.AIServiceDocumentClient(config=config)
)
endpoint_genai = "https://inference.generativeai.sa-saopaulo-1.oci.oraclecloud.com"
generative_ai_inference_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
    config=config, service_endpoint=endpoint_genai, retry_strategy=oci.retry.NoneRetryStrategy(), timeout=(10,240)
)
namespace = object_storage_client.get_namespace().data

# =========================================================================
# 2. FUNÇÃO AUXILIAR: CHAMADA À LLM (POR PÁGINA)
# =========================================================================

def corrigir_texto_com_llm(texto_pagina, numero_pagina):
    """Envia um pedaço de texto para a LLM corrigir"""
    if not texto_pagina.strip():
        return ""

    print(f"   > Processando página {numero_pagina} ({len(texto_pagina)} caracteres)...")

    prompt = f"""
    Atue como um especialista em transcrição. Abaixo está o texto cru (OCR) da página {numero_pagina} de um documento manuscrito.
    Sua missão: Corrigir erros de ortografia, pontuação e quebras de linha incorretas.
    Regra de Ouro: NÃO RESUMA. Mantenha integralmente o conteúdo. Se o texto parecer incompleto no fim, mantenha assim.
    
    Texto OCR:
    \"\"\"
    {texto_pagina}
    \"\"\"
    
    Texto Corrigido:
    """

    chat_detail = oci.generative_ai_inference.models.ChatDetails()
    content = oci.generative_ai_inference.models.TextContent()
    content.text = prompt
    
    chat_request = oci.generative_ai_inference.models.GenericChatRequest()
    chat_request.messages = [oci.generative_ai_inference.models.Message(role="USER", content=[content])]
    chat_request.max_tokens = 2000 
    chat_request.temperature = 0.1
    
    chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(
        model_id="ocid1.generativeaimodel.oc1.sa-saopaulo-1.amaaaaaask7dceyarsn4m6k3a....................."
    )
    chat_detail.chat_request = chat_request
    chat_detail.compartment_id = COMPARTMENT_ID

    try:
        response = generative_ai_inference_client.chat(chat_detail)
        return response.data.chat_response.choices[0].message.content[0].text
    except Exception as e:
        print(f"   [ERRO] Falha na página {numero_pagina}: {e}")
        return texto_pagina 

# =========================================================================
# 3. EXECUÇÃO DO OCR (DOCUMENT UNDERSTANDING)
# =========================================================================

print(f"--- 1. Iniciando OCR: {ARQUIVO_ALVO} ---")

text_feature = oci.ai_document.models.DocumentTextExtractionFeature()
input_location = oci.ai_document.models.ObjectStorageLocations(object_locations=[
    oci.ai_document.models.ObjectLocation(namespace_name=namespace, bucket_name=BUCKET_ORIGEM, object_name=ARQUIVO_ALVO)
])

# [CORRIGIDO] Voltamos para o nome output_location
output_location = oci.ai_document.models.OutputLocation(namespace_name=namespace, bucket_name=BUCKET_DESTINO, prefix="resultado_NPI")

job_details = oci.ai_document.models.CreateProcessorJobDetails(
    display_name=str(uuid.uuid4()), compartment_id=COMPARTMENT_ID,
    input_location=input_location, 
    output_location=output_location, # Agora a referência bate
    processor_config=oci.ai_document.models.GeneralProcessorConfig(features=[text_feature])
)

job_response = aiservicedocument_client.create_processor_job_and_wait_for_state(
    create_processor_job_details=job_details,
    wait_for_states=[oci.ai_document.models.ProcessorJob.LIFECYCLE_STATE_SUCCEEDED]
)
processor_job = job_response.data
print("OCR Concluído.")

# =========================================================================
# 4. DOWNLOAD E PROCESSAMENTO EM LOOP (CHUNK STRATEGY)
# =========================================================================

print("--- 2. Baixando JSON e Iniciando Correção com IA ---")

# [CORRIGIDO] Agora output_location está definido corretamente
json_path = "{}/{}/{}_{}/results/{}.json".format(
    output_location.prefix, processor_job.id, namespace, BUCKET_ORIGEM, ARQUIVO_ALVO
)
json_file = object_storage_client.get_object(namespace, BUCKET_DESTINO, json_path)
dados_json = json.loads(json_file.data.content.decode('utf-8'))

texto_ocr_completo = ""
texto_ia_completo = ""

if 'pages' in dados_json:
    total_paginas = len(dados_json['pages'])
    print(f"Documento contém {total_paginas} páginas. Iniciando processamento sequencial...")
    
    for i, page in enumerate(dados_json['pages']):
        linhas_pagina = []
        if 'lines' in page:
            for line in page['lines']:
                if 'text' in line:
                    linhas_pagina.append(line['text'])
        
        texto_pagina_bruto = "\n".join(linhas_pagina)
        texto_ocr_completo += texto_pagina_bruto + "\n\n" 
        
        if texto_pagina_bruto:
            texto_pagina_corrigido = corrigir_texto_com_llm(texto_pagina_bruto, i + 1)
            texto_ia_completo += texto_pagina_corrigido + "\n\n"
            time.sleep(1) 
        else:
            print(f"   > Página {i+1} vazia. Pulando.")

# =========================================================================
# 5. SALVAR E REPORTAR
# =========================================================================

print("\n--- 3. Salvando Resultado Final ---")

nome_final = ARQUIVO_ALVO.rsplit('.', 1)[0] + "_corrigido_completo.txt"
object_storage_client.put_object(
    namespace, BUCKET_DESTINO, nome_final,
    texto_ia_completo.encode('utf-8'), content_type="text/plain"
)
print(f"Arquivo salvo: {nome_final}")

def normalizar(txt):
    return re.sub(r'\s+', ' ', re.sub(r'[\n\r\t]', ' ', txt)).lower().strip()

s = SequenceMatcher(None, normalizar(texto_ocr_completo), normalizar(texto_ia_completo))
similaridade = s.ratio() * 100

print("\n================ RELATÓRIO FINAL ================")
print(f"Caracteres OCR (Entrada Total): {len(texto_ocr_completo)}")
print(f"Caracteres IA (Saída Total):    {len(texto_ia_completo)}")
print(f"Taxa de Similaridade:           {similaridade:.2f}%")

if abs(len(texto_ocr_completo) - len(texto_ia_completo)) > 2000:
    print(">> ALERTA: Diferença de tamanho relevante. Verifique se a IA não resumiu.")
else:
    print(">> SUCESSO: Tamanhos compatíveis. Processamento completo.")
