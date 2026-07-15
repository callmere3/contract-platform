// Форма повторяет реальный ответ GET /templates/{id}/fields (см. template_analysis.py):
// плоский список полей с полем `group`, порядок — как приходит с сервера.
// Это МОК конкретно для шаблона ПРИЛ_СГ_РОЯЛТИ — у другого шаблона будет
// другой набор полей/групп, DocFormPage их не знает заранее.
export const MOCK_TEMPLATE_SCHEMA = [
  {
    name: 'contract_number',
    label: 'Номер договора',
    type: 'text',
    group: 'ДОКУМЕНТ',
    default: 'МЛ-23/10/24-ИМЖ/СГ',
    hint: 'Номер договора зафиксирован в карточке контрагента и не редактируется здесь.',
    readOnly: true,
  },
  {
    name: 'doc_date',
    label: 'Дата документа',
    type: 'date',
    group: 'ДОКУМЕНТ',
    default: '2026-07-14',
    hint: 'дата этого Приложения/Акта — может отличаться от даты договора',
  },
  {
    name: 'annex_number',
    label: 'Номер приложения',
    type: 'text',
    group: 'ДОКУМЕНТ',
    default: '1',
  },
  {
    name: 'term_end',
    label: 'Срок действия',
    type: 'text',
    group: 'ДОКУМЕНТ',
    default: '30 сентября 2031 г.',
    hint: 'предзаполняется как дата документа +5 лет до конца квартала — можно поправить вручную',
    // TODO: автозаполнение по computeTermEndRu(doc_date) — расчётная
    // логика переносится отдельно, здесь только статичный default.
  },
  {
    name: 'full_name',
    label: 'ФИО полностью',
    type: 'text',
    group: 'КОНТРАГЕНТ',
    default: 'Ибара Мишель Жоржевич',
    hint: 'Иванов Иван Иванович',
  },
  {
    name: 'inn',
    label: 'ИНН',
    type: 'text',
    group: 'КОНТРАГЕНТ',
    default: '771234567890',
    hint: '771234567890',
  },
  {
    name: 'nickname',
    label: 'Псевдоним',
    type: 'choice',
    group: 'КОНТРАГЕНТ',
    choices: [{ value: 'RE3', label: 'RE3' }],
    hint: 'если нет — оставьте пустым',
  },
  {
    name: 'release_type',
    label: 'Тип релиза',
    type: 'choice',
    group: 'РЕЛИЗ',
    choices: [
      { value: 'single', label: 'Сингл' },
      { value: 'album', label: 'Альбом' },
      { value: 'ep', label: 'EP' },
    ],
  },
  {
    name: 'has_video',
    label: 'Есть видеоклип',
    type: 'flag',
    group: 'РЕЛИЗ',
    hint: 'если нет — пункт про клип удалится, нумерация сдвинется',
    asCard: true, // визуально — чекбокс-карточка, а не голый инлайн
  },
  {
    name: 'tracks',
    label: 'Список треков',
    type: 'list',
    group: 'ТРЕКИ',
    item_fields: [
      { name: 'name', label: 'НАЗВАНИЕ' },
      { name: 'music_author', label: 'АВТОР МУЗЫКИ' },
      { name: 'text_author', label: 'АВТОР ТЕКСТА' },
      { name: 'performer', label: 'ИСПОЛНИТЕЛЬ' },
      { name: 'producer_duration', label: 'ИЗГОТОВИТЕЛЬ / ХРОНОМЕТРАЖ' },
      { name: 'author_share', label: 'ДОЛЯ АВТОРСКАЯ' },
      { name: 'related_share', label: 'ДОЛЯ СМЕЖНАЯ' },
    ],
  },
  {
    name: 'performers',
    label: 'Исполнители (для сноски)',
    type: 'list',
    group: 'ТРЕКИ',
    item_fields: [
      { name: 'performer', label: 'ИСПОЛНИТЕЛЬ' },
      { name: 'fio', label: 'ФИО' },
    ],
  },
  {
    // is_group — флаг, но должен рендериться СРАЗУ ПОД таблицей исполнителей,
    // а не среди обычных полей группы (см. renderForm в текущем проде).
    name: 'is_group',
    label: 'Исполнитель — группа',
    type: 'flag',
    group: 'ТРЕКИ',
    hint: 'название группы берётся из никнейма в колонке «Исполнитель», ниже перечислите ФИО участников',
  },
];
