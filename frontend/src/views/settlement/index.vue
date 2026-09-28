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
        <strong class="stat-value">{{ formatStat(item) }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>结算单号</span>
        <input v-model="filters.keyword" placeholder="按结算单号检索" />
      </label>
      <label class="filter-item">
        <span>关联协议</span>
        <input v-model="filters.关联协议" placeholder="按关联协议检索" />
      </label>
      <label class="filter-item">
        <span>结算周期</span>
        <input v-model="filters.结算周期" placeholder="按结算周期检索" />
      </label>
      <label class="filter-item">
        <span>结算状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
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
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              :class="{ danger: action === '驳回结算' }"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的保障结算数据，可先登记结算单</td>
        </tr>
      </tbody>
    </table>

    <h3 class="summary-title">按结算周期汇总（与上方列表同一筛选口径）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in periodColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="group in periodStats" :key="group.结算周期">
          <td>{{ group.结算周期 }}</td>
          <td>{{ group.单据数 }}</td>
          <td>¥ {{ formatAmount(group.应付金额合计) }}</td>
          <td>¥ {{ formatAmount(group.已付金额合计) }}</td>
        </tr>
        <tr v-if="!periodStats.length">
          <td :colspan="periodColumns.length" class="empty-state">当前筛选条件下没有可汇总的结算单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条保障结算记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="createVisible" class="modal-mask" @click.self="closeCreate">
      <div class="modal-card">
        <h3>登记结算单</h3>
        <label v-for="field in createFields" :key="field.key" class="modal-field">
          <span>{{ field.label }}</span>
          <input v-model="createForm[field.key]" :type="field.type ?? 'text'" :placeholder="`请输入${field.label}`" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">登记</button>
        </div>
      </div>
    </div>

    <div v-if="payVisible" class="modal-mask" @click.self="closePay">
      <div class="modal-card">
        <h3>确认付款 · {{ payTarget?.['结算单号'] }}</h3>
        <p class="modal-tip">
          应付 ¥{{ formatAmount(payTarget?.['应付金额']) }}，累计已付 ¥{{ formatAmount(payTarget?.['已付金额']) }}，
          剩余可付 ¥{{ remainingPayable }}
        </p>
        <label class="modal-field">
          <span>付款编号</span>
          <input v-model="payForm.付款编号" placeholder="如 PAY-2026-0928-01" />
        </label>
        <label class="modal-field">
          <span>本次付款金额</span>
          <input v-model="payForm.付款金额" type="number" min="0" step="0.01" placeholder="不能超过剩余可付金额" />
        </label>
        <label class="modal-field">
          <span>付款日期</span>
          <input v-model="payForm.付款日期" type="date" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closePay">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitPay">确认付款</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | PaymentRecord[]>
type PaymentRecord = { 付款编号: string; 付款金额: number; 付款日期: string }
type StatCard = { label: string; value: number }
type PeriodGroup = { 结算周期: string; 单据数: number; 应付金额合计: number; 已付金额合计: number }

const ENDPOINT = '/api/settlement'
const columns = ['结算单号', '关联协议', '结算周期', '应付金额', '已付金额', '审核人员', '付款日期', '结算状态']
const periodColumns = ['结算周期', '单据数', '应付金额合计', '已付金额合计']
const statuses = ['待核算', '待审核', '已付款']
const actionSubmit = '提交审核'
const actionPay = '确认付款'
const actionReject = '驳回结算'

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: '待审核结算', value: 0 },
  { label: '本月付款金额', value: 0 },
  { label: '已驳回单据', value: 0 },
])
const periodStats = ref<PeriodGroup[]>([])
const errorMessage = ref('')
const filters = reactive<Record<string, string>>({ keyword: '', 关联协议: '', 结算周期: '', status: '' })

const createVisible = ref(false)
const payVisible = ref(false)
const submitting = ref(false)
const payTarget = ref<Row | null>(null)
const createFields = [
  { key: '结算单号', label: '结算单号' },
  { key: '关联协议', label: '关联协议' },
  { key: '结算周期', label: '结算周期（如 2026-09）' },
  { key: '应付金额', label: '应付金额', type: 'number' },
]
const createForm = reactive<Record<string, string>>({ 结算单号: '', 关联协议: '', 结算周期: '', 应付金额: '' })
const payForm = reactive<Record<string, string>>({ 付款编号: '', 付款金额: '', 付款日期: today() })

const remainingPayable = computed(() => {
  if (!payTarget.value) return '0.00'
  const payable = Number(payTarget.value['应付金额'] ?? 0)
  const paid = Number(payTarget.value['已付金额'] ?? 0)
  return formatAmount(Math.max(payable - paid, 0))
})

function today() {
  return new Date().toISOString().slice(0, 10)
}

function formatAmount(value: unknown) {
  const amount = Number(value ?? 0)
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00'
}

function formatStat(item: StatCard) {
  return item.label.includes('金额') ? `¥ ${formatAmount(item.value)}` : item.value
}

function displayCell(row: Row, column: string) {
  if (column === '应付金额' || column === '已付金额') {
    return `¥ ${formatAmount(row[column])}`
  }
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function availableActions(row: Row) {
  switch (row['status']) {
    case '待核算':
      return [actionSubmit]
    case '待审核':
      return [actionPay, actionReject]
    default:
      return []
  }
}

function buildQuery() {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value.trim()) params.set(key === 'keyword' ? 'keyword' : key, value.trim())
  })
  return params.toString()
}

function resetFilters() {
  Object.keys(filters).forEach((key) => {
    filters[key] = ''
  })
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.forEach((field) => {
    createForm[field.key] = ''
  })
  createVisible.value = true
}

function closeCreate() {
  createVisible.value = false
}

function closePay() {
  payVisible.value = false
  payTarget.value = null
}

async function submitCreate() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          结算单号: createForm['结算单号'],
          关联协议: createForm['关联协议'],
          结算周期: createForm['结算周期'],
          应付金额: createForm['应付金额'],
        },
      }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '结算单登记未生效，请稍后重试')
    }
    createVisible.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结算单登记失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  if (action === actionPay) {
    payTarget.value = row
    payForm.付款编号 = ''
    payForm.付款金额 = ''
    payForm.付款日期 = today()
    payVisible.value = true
    return
  }
  if (action === actionReject && !window.confirm(`确认驳回结算单 ${row['结算单号']}？将退回待核算并清空本次付款信息。`)) {
    return
  }
  const ok = await postAction(row.id as number, { action })
  if (ok) await reload()
}

async function submitPay() {
  if (!payTarget.value) return
  errorMessage.value = ''
  const id = payTarget.value.id as number
  const values: Record<string, string> = {
    action: actionPay,
    付款编号: payForm.付款编号,
    付款金额: payForm.付款金额,
  }
  if (payForm.付款日期) values.付款日期 = payForm.付款日期
  const ok = await postAction(id, values)
  if (!ok) {
    // 付款失败（超额、编号重复等）时弹窗保留，输入不丢，方便调整后重试
    payTarget.value = rows.value.find((item) => item.id === id) ?? payTarget.value
    return
  }
  closePay()
  await reload()
}

async function postAction(id: number, values: Record<string, string>) {
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '保障结算动作未生效，请稍后重试')
    }
    return true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障结算操作失败'
    return false
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  const suffix = query ? `?${query}` : ''
  try {
    const [listResponse, summaryResponse] = await Promise.all([
      request(`${ENDPOINT}${suffix}`),
      request(`${ENDPOINT}/summary${suffix}`),
    ])
    if (!listResponse.ok) throw new Error('结算单列表读取失败')
    if (!summaryResponse.ok) throw new Error('结算汇总读取失败')
    const listPayload = await listResponse.json()
    const summaryPayload = await summaryResponse.json()
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    stats.value = summaryPayload.cards ?? stats.value
    periodStats.value = summaryPayload.periods ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障结算列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
}
.summary-title {
  font-size: 14px;
  margin: 18px 0 8px;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.link.danger {
  color: #b42318;
}
.filter-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
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
  margin: 0 0 12px;
  font-size: 15px;
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
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 13px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
