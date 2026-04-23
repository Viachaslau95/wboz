{{- define "wboz.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "wboz.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "wboz.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "wboz.labels" -}}
app.kubernetes.io/name: {{ include "wboz.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "wboz.selectorLabels" -}}
app.kubernetes.io/name: {{ include "wboz.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "wboz.postgresServiceName" -}}
{{ include "wboz.fullname" . }}-postgres
{{- end -}}

{{- define "wboz.apiServiceName" -}}
{{ include "wboz.fullname" . }}-api
{{- end -}}
