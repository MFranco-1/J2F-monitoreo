import { Component, OnInit, inject, signal } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MasterDataService } from '../../../core/services/master-data.service';
import { UserService } from '../../../core/services/user.service';
import { Client, Vehicle, MasterKind } from '../../../shared/models/master-data.model';
import { State } from '../../../shared/models/user.model';

@Component({ selector:'app-master-data', standalone:true, imports:[NgFor,NgIf,FormsModule],
  templateUrl:'./master-data.component.html', styleUrl:'./master-data.component.scss' })
export class MasterDataComponent implements OnInit {
  private service=inject(MasterDataService); private users=inject(UserService);
  readonly tabs:{kind:MasterKind;label:string}[]=[{kind:'clients',label:'Clientes'},{kind:'vehicles',label:'Vehículos'},
    {kind:'gps-devices',label:'Dispositivos GPS'},{kind:'event-types',label:'Tipos de evento'}];
  kind:MasterKind='clients'; records=signal<any[]>([]); states=signal<State[]>([]);
  clients=signal<Client[]>([]); vehicles=signal<Vehicle[]>([]); loading=signal(true);
  showModal=signal(false); saving=signal(false); editing=signal<any|null>(null); error=signal(''); success=signal(''); form:any={};
  ngOnInit(){ this.users.getProfiles().subscribe(({states})=>this.states.set(states)); this.loadReferences(); this.load(); }
  select(kind:MasterKind){ this.kind=kind; this.loadReferences(); this.load(); }
  load(){ this.loading.set(true); this.service.list<any>(this.kind).subscribe({next:data=>{this.records.set(data[this.kind.replace('-','_')]||[]);this.loading.set(false);},error:e=>{this.error.set(e?.error?.error||'No se pudieron cargar los datos');this.loading.set(false);}}); }
  loadReferences(){ this.service.clients(false).subscribe(d=>this.clients.set(d['clients']||[])); this.service.vehicles(undefined,false).subscribe(d=>this.vehicles.set(d['vehicles']||[])); }
  blank(){ const state_id=this.states().find(s=>s.name==='Activo')?.id;
    return this.kind==='clients'?{document_type:'RUC',document_number:'',business_name:'',contact_name:'',phone:'',email:'',address:'',state_id}:
      this.kind==='vehicles'?{client_id:null,plate:'',brand:'',model:'',color:'',vehicle_type:'',state_id}:
      this.kind==='gps-devices'?{vehicle_id:null,imei:'',serial_number:'',model:'',provider:'',sim_number:'',state_id}:
      {code:'',name:'',description:'',default_priority:'medium',generates_alert:true,expected_action:'',state_id}; }
  open(record:any=null){this.editing.set(record);this.form=record?{...record}:{...this.blank()};this.error.set('');this.showModal.set(true);}
  close(){if(!this.saving())this.showModal.set(false);}
  save(){if(this.saving())return;this.saving.set(true);const item=this.editing();const request=item?this.service.update(this.kind,item.id,this.form):this.service.create(this.kind,this.form);
    request.subscribe({next:r=>{this.saving.set(false);this.success.set(r.message);this.showModal.set(false);this.loadReferences();this.load();setTimeout(()=>this.success.set(''),3000);},error:e=>{this.saving.set(false);this.error.set(e?.error?.error||'No se pudo guardar');}});}
  remove(record:any){if(!confirm('¿Eliminar este registro? Si tiene relaciones, deberá cambiarlo a Inactivo.'))return;this.service.delete(this.kind,record.id).subscribe({next:r=>{this.success.set(r.message);this.load();},error:e=>this.error.set(e?.error?.error||'No se pudo eliminar')});}
  title(record:any){return record.business_name||record.plate||record.imei||record.name;}
  detail(record:any){return record.document_number||[record.brand,record.model].filter(Boolean).join(' ')||record.serial_number||record.code;}
}
