import {CatalogEngine} from './catalog-client.js';
const engine=new CatalogEngine();
self.onmessage=async({data:{id,type,payload}})=>{
  try{
    if(!['query','resolve'].includes(type))throw Error('Unknown catalog operation.');
    const result=await engine[type](payload,(done,total)=>self.postMessage({id,progress:[done,total]}));
    self.postMessage({id,result});
  }catch(error){self.postMessage({id,error:error.message});}
};
