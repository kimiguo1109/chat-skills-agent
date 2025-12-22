/**
 * FileUpload - 文件上传组件
 * 
 * 支持上传文件到 GCS (gs://kimi-dev/)
 * 返回 file_uri 供 chat 接口使用
 */
import { useState, useRef, useCallback } from 'react'
import { API_BASE_URL } from '../../api/config'

interface FileUploadProps {
  onFileUploaded: (fileUri: string, fileName: string) => void
  onError?: (error: string) => void
  disabled?: boolean
  userId?: string
}

interface UploadResponse {
  code: number
  msg: string
  data?: {
    file_uri: string
    original_name: string
    size: number
    content_type: string
    mock?: boolean
  }
}

// 支持的文件类型
const ALLOWED_EXTENSIONS = [
  '.txt', '.pdf', '.doc', '.docx',  // 文档
  '.jpg', '.jpeg', '.png', '.gif', '.webp',  // 图片
  '.md', '.csv', '.json'  // 其他
]

const MAX_FILE_SIZE = 10 * 1024 * 1024  // 10MB

export function FileUpload({ 
  onFileUploaded, 
  onError, 
  disabled = false,
  userId = 'anonymous'
}: FileUploadProps) {
  const [isUploading, setIsUploading] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<{ name: string; uri: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    // 验证文件类型
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      onError?.(`不支持的文件类型: ${ext}. 支持: ${ALLOWED_EXTENSIONS.join(', ')}`)
      return
    }

    // 验证文件大小
    if (file.size > MAX_FILE_SIZE) {
      onError?.(`文件过大. 最大: ${MAX_FILE_SIZE / (1024 * 1024)}MB`)
      return
    }

    setIsUploading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('user_id', userId)

      const response = await fetch(`${API_BASE_URL}/api/external/upload`, {
        method: 'POST',
        body: formData,
      })

      const result: UploadResponse = await response.json()

      if (result.code !== 0 || !result.data) {
        throw new Error(result.msg || '上传失败')
      }

      const { file_uri, original_name } = result.data
      
      setUploadedFile({ name: original_name, uri: file_uri })
      onFileUploaded(file_uri, original_name)

      // 如果是 mock 模式，显示提示
      if (result.data.mock) {
        console.warn('⚠️ GCS 未配置，使用模拟 URI')
      }

    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '上传失败'
      onError?.(errorMsg)
      console.error('文件上传失败:', error)
    } finally {
      setIsUploading(false)
      // 重置 input，允许重新选择相同文件
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }, [onFileUploaded, onError, userId])

  const handleClick = () => {
    if (!disabled && !isUploading) {
      fileInputRef.current?.click()
    }
  }

  const handleRemoveFile = () => {
    setUploadedFile(null)
    onFileUploaded('', '')
  }

  return (
    <div className="flex items-center gap-2">
      {/* 隐藏的文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept={ALLOWED_EXTENSIONS.join(',')}
        onChange={handleFileSelect}
        disabled={disabled || isUploading}
      />
      
      {/* 上传按钮 */}
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || isUploading}
        className={`
          flex items-center justify-center size-8 rounded-lg
          transition-colors
          ${isUploading 
            ? 'bg-gray-300 cursor-wait' 
            : uploadedFile 
              ? 'bg-green-500 text-white hover:bg-green-600' 
              : 'bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark hover:bg-gray-100 dark:hover:bg-gray-700'
          }
          disabled:opacity-50 disabled:cursor-not-allowed
        `}
        title={uploadedFile ? `已上传: ${uploadedFile.name}` : '上传附件'}
      >
        {isUploading ? (
          <span className="material-symbols-outlined text-lg animate-spin">sync</span>
        ) : uploadedFile ? (
          <span className="material-symbols-outlined text-lg">check</span>
        ) : (
          <span className="material-symbols-outlined text-lg">attach_file</span>
        )}
      </button>

      {/* 已上传文件显示 */}
      {uploadedFile && (
        <div className="flex items-center gap-1 px-2 py-1 bg-green-100 dark:bg-green-900/30 rounded-lg text-sm">
          <span className="text-green-700 dark:text-green-300 truncate max-w-32" title={uploadedFile.name}>
            {uploadedFile.name}
          </span>
          <button
            type="button"
            onClick={handleRemoveFile}
            className="text-green-600 dark:text-green-400 hover:text-red-500 transition-colors"
            title="移除文件"
          >
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
        </div>
      )}
    </div>
  )
}

export default FileUpload


