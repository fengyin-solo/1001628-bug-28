<template>
  <section class="page" data-module="settlement">
    <header class="page-head">
      <div>
        <h2>保障结算管理</h2>
        <p class="page-desc">维护结算单，围绕结算单号、关联协议、结算周期、应付金额做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记结算单</button>
        <button class="btn" type="button" @click="exportRows">导出保障结算清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input
          v-if="field === '结算周期'"
          v-model="filters[field]"
          type="month"
        />
        <input v-else v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>结算状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保障结算数据，可先登记结算单</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">按结算周期汇总</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in periodColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="bucket in periodStats" :key="bucket['结算周期']">
          <td>{{ bucket['结算周期'] }}</td>
          <td>{{ bucket['单据数'] }}</td>
          <td>{{ formatAmount(bucket['应付金额']) }}</td>
          <td>{{ formatAmount(bucket['已付金额']) }}</td>
        </tr>
        <tr v-if="!periodStats.length">
          <td :colspan="periodColumns.length" class="empty-state">当前筛选条件下暂无周期汇总</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条保障结算记录</span>
      <span v-if="successMessage" class="success-text">{{ successMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="payDialog.open" class="modal-mask" @click.self="closePayDialog">
      <form class="modal-card" @submit.prevent="submitPay">
        <h3>确认付款 · {{ payDialog.row?.['结算单号'] }}</h3>
        <p class="modal-tip">
          应付 {{ formatAmount(payDialog.row?.['应付金额']) }} 元，
          已付 {{ formatAmount(payDialog.row?.['已付金额']) }} 元，
          剩余 {{ formatAmount(remainingAmount) }} 元；累计已付不能超过应付。
        </p>
        <label class="modal-field">
          <span>本次付款金额（元）</span>
          <input v-model="payDialog.amount" type="number" min="0" step="0.01" placeholder="如 1000.00" required />
        </label>
        <label class="modal-field">
          <span>付款日期</span>
          <input v-model="payDialog.date" type="date" required />
        </label>
        <label class="modal-field">
          <span>审核人员</span>
          <input v-model="payDialog.auditor" type="text" placeholder="可选，默认沿用原审核人员" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closePayDialog">取消</button>
          <button class="btn primary" type="submit">确认付款</button>
        </div>
      </form>
    </div>

    <div v-if="createDialog.open" class="modal-mask" @click.self="closeCreateDialog">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记结算单</h3>
        <label class="modal-field">
          <span>结算单号</span>
          <input v-model="createDialog.code" type="text" placeholder="如 SETT-0005" required />
        </label>
        <label class="modal-field">
          <span>关联协议</span>
          <input v-model="createDialog.agreement" type="text" placeholder="如 AGRE-0001" required />
        </label>
        <label class="modal-field">
          <span>结算周期</span>
          <input v-model="createDialog.period" type="month" required />
        </label>
        <label class="modal-field">
          <span>应付金额（元）</span>
          <input v-model="createDialog.payable" type="number" min="0" step="0.01" placeholder="如 2000.00" required />
        </label>
        <label class="modal-field">
          <span>审核人员</span>
          <input v-model="createDialog.auditor" type="text" placeholder="可选" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeCreateDialog">取消</button>
          <button class="btn primary" type="submit">登记</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type PeriodBucket = { '结算周期': string; '单据数': number; '应付金额': number; '已付金额': number }

const ENDPOINT = '/api/settlement'
const columns = ['结算单号', '关联协议', '结算周期', '应付金额', '已付金额', '审核人员', '付款日期', '结算状态']
const periodColumns = ['结算周期', '单据数', '应付金额', '已付金额']
const statuses = ['待核算', '待审核', '已付款']
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待核算: ['提交审核'],
  待审核: ['确认付款', '驳回结算'],
  已付款: [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({ 结算单号: '', 关联协议: '', 结算周期: '' })
const statusFilter = ref('')
const FILTER_PARAMS: Record<string, string> = {
  结算单号: 'keyword',
  关联协议: 'agreement',
  结算周期: 'period',
}
const filterFields = columns.slice(0, 3)
// 汇总数字一律来自后端 /summary，与列表同筛选口径，刷新后仍以后端数据为准。
const stats = ref([
  { label: '待审核结算', value: 0 },
  { label: '本月付款金额', value: '¥0.00' },
  { label: '已驳回单据', value: 0 },
])
const periodStats = ref<PeriodBucket[]>([])

const payDialog = reactive({
  open: false,
  row: null as Row | null,
  amount: '',
  date: today(),
  auditor: '',
})
const createDialog = reactive({
  open: false,
  code: '',
  agreement: '',
  period: '',
  payable: '',
  auditor: '',
})

const remainingAmount = computed(() => {
  if (!payDialog.row) return 0
  return toNumber(payDialog.row['应付金额']) - toNumber(payDialog.row['已付金额'])
})

function today(): string {
  const now = new Date()
  const month = `${now.getMonth() + 1}`.padStart(2, '0')
  const day = `${now.getDate()}`.padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function toNumber(value: unknown): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : 0
}

function formatAmount(value: unknown): string {
  return `¥${toNumber(value).toFixed(2)}`
}

function displayValue(row: Row, column: string): string | number {
  const value = row[column]
  if (column === '应付金额' || column === '已付金额') return formatAmount(value)
  if ((column === '付款日期' || column === '审核人员') && (value === null || value === '' || value === undefined)) {
    return '—'
  }
  if (column === '结算状态') return String(row['status'] ?? value ?? '—')
  return (value ?? '—') as string | number
}

function availableActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function resetFilters() {
  filters.value = { 结算单号: '', 关联协议: '', 结算周期: '' }
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  Object.assign(createDialog, {
    open: true,
    code: '',
    agreement: '',
    period: '',
    payable: '',
    auditor: '',
  })
}

function closeCreateDialog() {
  createDialog.open = false
}

function closePayDialog() {
  payDialog.open = false
  payDialog.row = null
  payDialog.amount = ''
  payDialog.auditor = ''
  payDialog.date = today()
}

function buildQuery(): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) params.set(FILTER_PARAMS[key] ?? key, value)
  }
  if (statusFilter.value) params.set('status', statusFilter.value)
  const query = params.toString()
  return query ? `?${query}` : ''
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    if (payload?.detail) return String(payload.detail.message ?? payload.detail)
    if (payload?.message) return String(payload.message)
  } catch {
    // 非 JSON 错误体时回落到兜底文案
  }
  return fallback
}

async function reload() {
  errorMessage.value = ''
  successMessage.value = ''
  const query = buildQuery()
  try {
    const [listResponse, summaryResponse] = await Promise.all([
      request(`${ENDPOINT}${query}`),
      request(`${ENDPOINT}/summary${query}`),
    ])
    if (!listResponse.ok) {
      throw new Error(await readErrorMessage(listResponse, '结算单列表读取失败'))
    }
    if (!summaryResponse.ok) {
      throw new Error(await readErrorMessage(summaryResponse, '结算汇总读取失败'))
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const summary = await summaryResponse.json()
    stats.value = [
      { label: '待审核结算', value: Number(summary['待审核结算'] ?? 0) },
      { label: '本月付款金额', value: formatAmount(summary['本月付款金额'] ?? 0) },
      { label: '已驳回单据', value: Number(summary['已驳回单据'] ?? 0) },
    ]
    periodStats.value = Array.isArray(summary['周期汇总']) ? summary['周期汇总'] : []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障结算列表读取失败'
  }
}

function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  if (action === '确认付款') {
    payDialog.open = true
    payDialog.row = row
    payDialog.amount = ''
    payDialog.date = today()
    payDialog.auditor = String(row['审核人员'] ?? '')
    return
  }
  void postAction(action, row, {})
}

async function submitPay() {
  if (!payDialog.row) return
  const amount = Number(payDialog.amount)
  if (!Number.isFinite(amount) || amount <= 0) {
    errorMessage.value = '请输入大于 0 的本次付款金额'
    return
  }
  const row = payDialog.row
  const values = { action: '确认付款', 本次付款金额: amount, 付款日期: payDialog.date, 审核人员: payDialog.auditor }
  closePayDialog()
  await postAction('确认付款', row, values)
}

async function submitCreate() {
  const values = {
    结算单号: createDialog.code,
    关联协议: createDialog.agreement,
    结算周期: createDialog.period,
    应付金额: createDialog.payable,
    审核人员: createDialog.auditor,
  }
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      errorMessage.value = payload?.message || '结算单登记失败'
      return
    }
    closeCreateDialog()
    successMessage.value = payload.message || '结算单已登记'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结算单登记失败'
  }
}

async function postAction(action: string, row: Row, values: Record<string, unknown>) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...values } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '保障结算动作未生效，请稍后重试')
    }
    successMessage.value = payload.message || '操作已生效'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障结算操作失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title {
  font-size: 15px;
  margin: 18px 0 8px;
}
.success-text {
  color: #067647;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 380px;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
}
.modal-card h3 {
  margin: 0 0 10px;
  font-size: 16px;
}
.modal-tip {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--muted);
}
.modal-field {
  display: block;
  margin-bottom: 10px;
}
.modal-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-field input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>
