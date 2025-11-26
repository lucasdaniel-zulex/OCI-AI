import oci
import time
import json

# ConfiguraÃ§Ã£o OCI
config = oci.config.from_file("./config", "DEFAULT")
compartment_id = "ocid1.compartment.oc1..aaaaaaaaxsppaf4x6qpxm6awppta7g2wwhutmbf7ikjdmg35ijcatbwnxs5q"

namespace = "idi1o0a010nx"
bucket = "BucketIA"
object_name = "testaudiomusica.wav"
output_prefix = "transcricoes"

# Clientes OCI
object_storage = oci.object_storage.ObjectStorageClient(config)
speech = oci.ai_speech.AIServiceSpeechClient(config)

# Criar job de transcriÃ§Ã£o usando WHISPER LARGE V3 TURBO
job_response = speech.create_transcription_job(
    oci.ai_speech.models.CreateTranscriptionJobDetails(
        compartment_id=compartment_id,
        input_location=oci.ai_speech.models.ObjectListInlineInputLocation(
            location_type="OBJECT_LIST_INLINE_INPUT_LOCATION",
            object_locations=[
                oci.ai_speech.models.ObjectLocation(
                    namespace_name=namespace,
                    bucket_name=bucket,
                    object_names=[object_name]
                )
            ]
        ),
        output_location=oci.ai_speech.models.OutputLocation(
            namespace_name=namespace,
            bucket_name=bucket,
            prefix=output_prefix
        ),
        display_name="TranscricaoWhisperV3Turbo",

        # aqui sÃ£o os parametros para definir o modelo versÃ£o e linguagem
        model_details=oci.ai_speech.models.TranscriptionModelDetails(
            model_type="WHISPER",                  # Tipo WHISPER
            model_version="LARGE_V3_TURBO",        # VersÃ£o V3 Turbo
            domain="GENERIC",                      # Sempre GENERIC
            language_code="pt"                     # Whisper usa "pt", nÃ£o pt-BR
        ),

        normalization=oci.ai_speech.models.TranscriptionNormalization(
            is_punctuation_enabled=True
        )
    )
)

# Esperar finalizar
job_id = job_response.data.id
print(f"TranscriÃ§Ã£o iniciada com Whisper V3 Turbo (job_id={job_id})...")

while True:
    job = speech.get_transcription_job(job_id).data
    if job.lifecycle_state == "SUCCEEDED":
        break
    elif job.lifecycle_state == "FAILED":
        print("TranscriÃ§Ã£o falhou.")
        exit()
    time.sleep(1)

# Buscar resultado no bucket
objects = object_storage.list_objects(namespace, bucket, prefix=output_prefix)
for obj in objects.data.objects:
    if obj.name.endswith(object_name + ".json"):
        result = object_storage.get_object(namespace, bucket, obj.name)
        data = json.loads(result.data.text)
        texto = data['transcriptions'][0]['transcription']
        confianca = float(data['transcriptions'][0]['confidence']) * 100

        print("\n--- TranscriÃ§Ã£o (WHISPER V3 TURBO) ---")
        print(texto)
        pri