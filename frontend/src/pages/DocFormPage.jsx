import { useMemo, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { SectionLabel } from '../components/ui/Field';
import { FieldRenderer } from '../components/ui/FieldRenderer';
import { CheckboxCard, InlineCheckbox } from '../components/ui/CheckboxCard';
import { EditableTable } from '../components/ui/EditableTable';
import { MOCK_TEMPLATE_SCHEMA } from './mockTemplateSchema';

let nextRowId = 1000;
const makeListRow = (fields = {}) => ({ id: nextRowId++, ...fields });

// Группируем поля по f.group, СОХРАНЯЯ порядок с сервера — как в
// текущем renderForm(fields) из backend/static/index.html.
function groupFields(schema) {
  const order = [];
  const byGroup = new Map();
  schema.forEach((f) => {
    if (!byGroup.has(f.group)) {
      byGroup.set(f.group, []);
      order.push(f.group);
    }
    byGroup.get(f.group).push(f);
  });
  return order.map((group) => ({ group, fields: byGroup.get(group) }));
}

export function DocFormPage({
  templateCode = 'ПРИЛ_СГ_РОЯЛТИ',
  schema = MOCK_TEMPLATE_SCHEMA,
  contragent,
  onBack,
  onGenerate,
}) {
  const groups = useMemo(() => groupFields(schema), [schema]);

  // Префилл из карточки контрагента (applyContragentPrefill в текущем проде) —
  // не трогает default из схемы, если контрагент не передан (открыли форму
  // напрямую из папки, без выбора контрагента).
  const [values, setValues] = useState(() => {
    if (!contragent) return {};
    const prefill = {
      full_name: contragent.fullName ?? contragent.name,
      inn: contragent.inn,
      nickname: contragent.alias,
      contract_number: contragent.contractNumber,
    };
    return Object.fromEntries(Object.entries(prefill).filter(([, v]) => v != null));
  });
  const [listRows, setListRows] = useState(() => {
    const initial = {};
    schema
      .filter((f) => f.type === 'list')
      .forEach((f) => {
        initial[f.name] = [makeListRow()];
      });
    return initial;
  });
  const [alsoGenerateAct, setAlsoGenerateAct] = useState(true);
  const [format, setFormat] = useState('docx');

  const setValue = (name, value) => setValues((v) => ({ ...v, [name]: value }));

  const updateListCell = (listName, rowId, key, value) =>
    setListRows((rows) => ({
      ...rows,
      [listName]: rows[listName].map((r) => (r.id === rowId ? { ...r, [key]: value } : r)),
    }));

  const addListRow = (listName) =>
    setListRows((rows) => ({ ...rows, [listName]: [...rows[listName], makeListRow()] }));

  const removeListRow = (listName, rowId) =>
    setListRows((rows) => ({
      ...rows,
      [listName]: rows[listName].filter((r) => r.id !== rowId),
    }));

  const handleGenerate = () => {
    onGenerate?.({ values, listRows, alsoGenerateAct, format });
  };

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        {/* Шапка карточки */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <span className="text-[13px] font-bold tracking-[0.04em] text-text">
            {templateCode}
          </span>
          <button
            onClick={onBack}
            className="cursor-pointer text-[13px] text-text-secondary border border-border rounded-input px-3.5 py-2 bg-transparent"
          >
            ← К выбору шаблона
          </button>
        </div>

        {groups.map(({ group, fields }) => {
          // is_group рендерится отдельно, СРАЗУ ПОД таблицей исполнителей —
          // не в общей сетке полей (см. комментарий в mockTemplateSchema.js).
          const isGroupField = fields.find((f) => f.name === 'is_group');
          const lists = fields.filter((f) => f.type === 'list');
          const plain = fields.filter((f) => f.type !== 'list' && f.name !== 'is_group');

          return (
            <div key={group} className="px-6 py-7 border-b border-border last:border-b-0">
              <SectionLabel>{group}</SectionLabel>

              {plain.length > 0 && (
                <div
                  className="grid gap-5 items-start mb-2 last:mb-0"
                  style={{
                    gridTemplateColumns: `repeat(auto-fill, minmax(180px, 1fr))`,
                  }}
                >
                  {plain.map((field) =>
                    field.asCard ? (
                      <CheckboxCard
                        key={field.name}
                        label={field.label}
                        hint={field.hint}
                        checked={!!values[field.name]}
                        onChange={(e) => setValue(field.name, e.target.checked)}
                      />
                    ) : (
                      <FieldRenderer
                        key={field.name}
                        field={field}
                        value={values[field.name]}
                        onChange={(v) => setValue(field.name, v)}
                      />
                    )
                  )}
                </div>
              )}

              {lists.map((list) => (
                <div key={list.name} className={plain.length ? 'mt-6' : ''}>
                  <div className="text-[13px] font-semibold text-text mb-2">{list.label}</div>
                  <EditableTable
                    columns={list.item_fields.map((c) => ({ key: c.name, label: c.label }))}
                    rows={listRows[list.name] ?? []}
                    onChangeCell={(rowId, key, value) => updateListCell(list.name, rowId, key, value)}
                    onRemoveRow={(rowId) => removeListRow(list.name, rowId)}
                    onAddRow={() => addListRow(list.name)}
                  />
                </div>
              ))}

              {isGroupField && (
                <InlineCheckbox
                  label={isGroupField.label}
                  hint={isGroupField.hint}
                  checked={!!values[isGroupField.name]}
                  onChange={(e) => setValue(isGroupField.name, e.target.checked)}
                />
              )}

              {group === 'ТРЕКИ' && (
                <CheckboxCard
                  label="Также сформировать «Акт_СГ_роялти» по тем же данным"
                  hint="Использует те же данные формы — второй раз вводить не нужно."
                  checked={alsoGenerateAct}
                  onChange={(e) => setAlsoGenerateAct(e.target.checked)}
                />
              )}
            </div>
          );
        })}

        {/* ФУТЕР */}
        <div className="flex items-center gap-3 px-6 py-5">
          <Button variant="accent" size="sm" onClick={handleGenerate}>
            Сформировать документ
          </Button>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-[13px] text-text font-sans"
          >
            <option value="docx">Word (.docx)</option>
            <option value="pdf">PDF</option>
          </select>
        </div>
      </Card>
    </div>
  );
}
